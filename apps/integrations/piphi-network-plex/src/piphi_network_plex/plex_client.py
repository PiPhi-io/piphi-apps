from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from .settings import INTEGRATION_VERSION


@dataclass(slots=True, frozen=True)
class PlexServer:
    machine_id: str
    name: str
    base_url: str
    token: str
    owned: bool = True
    local: bool = True
    relay: bool = False


class PlexClient:
    """Small async Plex API client with JSON/XML normalization."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        verify_tls: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.transport = transport

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Plex-Token": token,
            "X-Plex-Client-Identifier": "piphi-network-plex",
            "X-Plex-Product": "PiPhi Network Plex",
            "X-Plex-Version": INTEGRATION_VERSION,
        }

    async def request(self, server: PlexServer, path: str, *, params: dict[str, Any] | None = None, method: str = "GET") -> dict[str, Any]:
        target = f"{server.base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(
            timeout=self.timeout,
            verify=self.verify_tls,
            transport=self.transport,
        ) as client:
            response = await client.request(method, target, params=params, headers=self._headers(server.token))
            response.raise_for_status()
            if not response.content:
                return {"ok": True}
            if "json" in response.headers.get("content-type", ""):
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            return self._xml_payload(response.text)

    async def bytes(self, server: PlexServer, path: str) -> tuple[bytes, str]:
        target = f"{server.base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(
            timeout=self.timeout,
            verify=self.verify_tls,
            transport=self.transport,
        ) as client:
            response = await client.get(target, headers=self._headers(server.token))
            response.raise_for_status()
            return response.content, response.headers.get("content-type", "application/octet-stream")

    async def discover(self, token: str, *, base_url: str = "", host: str = "", include_remote: bool = True) -> list[PlexServer]:
        if base_url or host:
            url = base_url or (host if "://" in host else f"http://{host}:32400")
            provisional = PlexServer("pending", host or url, url.rstrip("/"), token)
            root = await self.request(provisional, "/")
            container = root.get("MediaContainer", root)
            return [PlexServer(
                machine_id=str(container.get("machineIdentifier") or container.get("machine_identifier") or url),
                name=str(container.get("friendlyName") or container.get("friendly_name") or host or "Plex Server"),
                base_url=url.rstrip("/"), token=token,
            )]

        async with httpx.AsyncClient(
            timeout=self.timeout,
            verify=self.verify_tls,
            transport=self.transport,
        ) as client:
            response = await client.get(
                "https://plex.tv/api/v2/resources",
                params={"includeHttps": 1, "includeRelay": 1},
                headers={**self._headers(token), "Accept": "application/xml"},
            )
            response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        servers: list[PlexServer] = []
        for device in root.findall(".//Device"):
            if "server" not in str(device.attrib.get("provides", "")).split(","):
                continue
            connections = list(device.findall("Connection"))
            if not include_remote:
                connections = [item for item in connections if item.attrib.get("local") == "1"]
            connection = next((item for item in connections if item.attrib.get("local") == "1"), None)
            if connection is None:
                connection = next(
                    (item for item in connections if item.attrib.get("relay") != "1"),
                    None,
                )
            if connection is None and connections:
                connection = connections[0]
            if connection is None or not connection.attrib.get("uri"):
                continue
            servers.append(PlexServer(
                machine_id=str(device.attrib.get("clientIdentifier") or device.attrib.get("machineIdentifier") or ""),
                name=str(device.attrib.get("name") or "Plex Server"),
                base_url=str(connection.attrib["uri"]).rstrip("/"),
                token=str(device.attrib.get("accessToken") or token),
                owned=device.attrib.get("owned", "1") == "1",
                local=connection.attrib.get("local", "0") == "1",
                relay=connection.attrib.get("relay", "0") == "1",
            ))
        return [server for server in servers if server.machine_id]

    @staticmethod
    def media_container(payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("MediaContainer", payload)
        return value if isinstance(value, dict) else {}

    @classmethod
    def metadata(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        container = cls.media_container(payload)
        hubs = container.get("Hub")
        if isinstance(hubs, list):
            flattened: list[dict[str, Any]] = []
            for hub in hubs:
                if not isinstance(hub, dict):
                    continue
                flattened.extend(cls.metadata({"MediaContainer": hub}))
            if flattened:
                return flattened
        for key in ("Metadata", "Directory", "Video", "Track", "Photo"):
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        return []

    @staticmethod
    def _xml_payload(source: str) -> dict[str, Any]:
        root = ElementTree.fromstring(source)
        def convert(element: ElementTree.Element) -> dict[str, Any]:
            result: dict[str, Any] = dict(element.attrib)
            for child in element:
                result.setdefault(child.tag, []).append(convert(child))
            return result
        return {"MediaContainer": convert(root)}


def normalize_item(item: dict[str, Any], *, config_id: str, server: PlexServer) -> dict[str, Any]:
    rating_key = str(item.get("ratingKey") or item.get("key") or item.get("id") or "")
    kind = str(item.get("type") or "unknown")
    title = str(item.get("title") or item.get("grandparentTitle") or "Untitled")
    artist = str(item.get("grandparentTitle") or item.get("parentTitle") or item.get("originalTitle") or "")
    thumb = str(item.get("thumb") or item.get("parentThumb") or item.get("grandparentThumb") or "")
    instance_id = f"{config_id}:{server.machine_id}"
    return {
        "id": f"plex:{instance_id}:{rating_key}",
        "provider": "plex",
        "provider_instance_id": instance_id,
        "provider_item_id": rating_key,
        "title": title,
        "artist": artist,
        "album": str(item.get("parentTitle") or ""),
        "kind": kind,
        "thumbnail": f"/provider/{quote(instance_id, safe='')}/asset?path={quote(thumb, safe='')}" if thumb else "",
        "artwork_url": f"/provider/{quote(instance_id, safe='')}/asset?path={quote(thumb, safe='')}" if thumb else "",
        "duration_seconds": int(item.get("duration") or 0) // 1000 or None,
        "view_offset_seconds": int(item.get("viewOffset") or 0) // 1000,
        "view_count": int(item.get("viewCount") or 0),
        "year": item.get("year"),
        "summary": str(item.get("summary") or ""),
        "playable": kind in {"movie", "episode", "track", "clip", "video"},
    }


def normalize_collection(item: dict[str, Any], *, config_id: str, server: PlexServer) -> dict[str, Any]:
    key = str(item.get("ratingKey") or item.get("key") or item.get("id") or "")
    instance_id = f"{config_id}:{server.machine_id}"
    return {
        "id": key,
        "provider": "plex",
        "provider_instance_id": instance_id,
        "kind": str(item.get("type") or "library"),
        "title": str(item.get("title") or item.get("name") or "Plex Library"),
        "subtitle": str(item.get("type") or ""),
        "item_count": int(item.get("leafCount") or item.get("childCount") or 0),
        "path": str(item.get("key") or ""),
    }
