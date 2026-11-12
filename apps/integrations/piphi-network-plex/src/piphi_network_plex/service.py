from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import schedule_telemetry_delivery

from .plex_client import PlexClient, PlexServer, normalize_collection, normalize_item
from .schemas import DeviceConfig
from .simulator import SimulatedPlexClient


@dataclass(slots=True)
class PlexConnection:
    config: DeviceConfig
    entry: dict[str, Any]
    servers: dict[str, PlexServer] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None
    error: str = ""


class PlexRuntimeService:
    def __init__(self, *, registry, runtime, telemetry, client: PlexClient | None = None):
        self.registry = registry
        self.runtime = runtime
        self.telemetry = telemetry
        self.client = client or PlexClient()
        self.simulator_client = SimulatedPlexClient()
        self.connections: dict[str, PlexConnection] = {}
        self._lock = asyncio.Lock()

    async def configure(self, config: DeviceConfig, entry: dict[str, Any]) -> None:
        config_id = str(entry["config_id"])
        async with self._lock:
            await self._remove_locked(config_id)
            connection = PlexConnection(config=config, entry=entry)
            self.connections[config_id] = connection
            self.registry.set(config_id, entry)
            await self.refresh(config_id)
            connection.task = asyncio.create_task(self._poll(connection), name=f"plex-poll-{config_id}")

    async def refresh(self, config_id: str) -> dict[str, Any]:
        connection = self.connections.get(config_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Unknown Plex configuration")
        try:
            client = self.simulator_client if connection.config.simulation_mode else self.client
            discovered = await client.discover(
                connection.config.token,
                base_url=connection.config.base_url,
                host=connection.config.host,
                include_remote=connection.config.include_remote_servers,
            )
            connection.servers = {server.machine_id: server for server in discovered}
            connection.error = ""
        except Exception as exc:
            connection.error = str(exc)
            if not connection.servers:
                self.registry.update_state(config_id, {"connected": False, "error": str(exc)}, device_id=str(connection.entry["device_id"]))
                return {"connected": False, "error": str(exc), "server_count": 0}
        sessions: list[dict[str, Any]] = []
        for server in connection.servers.values():
            try:
                client = self._client_for_server(server)
                payload = await client.request(server, "/status/sessions")
                for session in client.metadata(payload):
                    user = self._first_mapping(session.get("User"))
                    player = self._first_mapping(session.get("Player"))
                    sessions.append({
                        "server_id": server.machine_id,
                        "session_id": str(session.get("sessionKey") or session.get("ratingKey") or ""),
                        "title": str(session.get("title") or session.get("grandparentTitle") or "Unknown"),
                        "kind": str(session.get("type") or "unknown"),
                        "user": str(user.get("title") or session.get("user") or ""),
                        "player": str(player.get("title") or ""),
                        "state": str(player.get("state") or ""),
                        "transcode": bool(session.get("TranscodeSession")),
                    })
            except Exception:
                continue
        state = {
            "connected": bool(connection.servers),
            "server_count": len(connection.servers),
            "active_sessions": len(sessions),
            "transcode_sessions": sum(1 for session in sessions if session["transcode"]),
            "sessions": sessions,
            "servers": [self._public_server(config_id, server) for server in connection.servers.values()],
            "error": connection.error,
        }
        self.registry.update_state(config_id, state, device_id=str(connection.entry["device_id"]))
        schedule_telemetry_delivery(
            process_state=self.runtime.process_state,
            telemetry_client=self.telemetry,
            auth_context=self.runtime.auth,
            config_id=config_id,
            device_id=str(connection.entry["device_id"]),
            container_id=connection.entry.get("container_id"),
            metrics={key: state[key] for key in ("connected", "server_count", "active_sessions", "transcode_sessions")},
            units={"server_count": "servers", "active_sessions": "sessions", "transcode_sessions": "sessions"},
        )
        return state

    async def remove(self, config_id: str) -> bool:
        async with self._lock:
            existed = config_id in self.connections or self.registry.get(config_id) is not None
            await self._remove_locked(config_id)
            self.registry.remove(config_id)
            return existed

    async def close(self) -> None:
        async with self._lock:
            for config_id in list(self.connections):
                await self._remove_locked(config_id)

    async def _remove_locked(self, config_id: str) -> None:
        connection = self.connections.pop(config_id, None)
        if connection and connection.task and connection.task is not asyncio.current_task():
            connection.task.cancel()
            with suppress(asyncio.CancelledError):
                await connection.task

    async def _poll(self, connection: PlexConnection) -> None:
        config_id = str(connection.entry["config_id"])
        while self.connections.get(config_id) is connection:
            await asyncio.sleep(connection.config.poll_interval_seconds)
            await self.refresh(config_id)

    def instances(self, config_id: str | None = None) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for current_id, connection in self.connections.items():
            if config_id and current_id != config_id:
                continue
            values.extend(self._public_server(current_id, server) for server in connection.servers.values())
        return values

    def resolve_server(self, instance_id: str) -> tuple[str, PlexServer]:
        config_id, separator, machine_id = instance_id.partition(":")
        if not separator:
            raise HTTPException(status_code=400, detail="Invalid provider instance")
        connection = self.connections.get(config_id)
        server = connection.servers.get(machine_id) if connection else None
        if server is None:
            raise HTTPException(status_code=404, detail="Plex server is unavailable")
        return config_id, server

    async def collections(self, instance_id: str) -> list[dict[str, Any]]:
        config_id, server = self.resolve_server(instance_id)
        client = self._client_for_server(server)
        payload = await client.request(server, "/library/sections")
        return [normalize_collection(item, config_id=config_id, server=server) for item in client.metadata(payload)]

    async def items(self, instance_id: str, *, collection_id: str = "", hub: str = "", query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        config_id, server = self.resolve_server(instance_id)
        if query:
            path, params = "/hubs/search", {"query": query, "limit": limit}
        elif hub == "recently_added":
            path, params = "/library/recentlyAdded", {"X-Plex-Container-Size": limit}
        elif hub == "on_deck":
            path, params = "/library/onDeck", {"X-Plex-Container-Size": limit}
        elif hub == "continue_watching":
            path, params = "/hubs/continueWatching", {"count": limit}
        elif collection_id:
            path, params = f"/library/sections/{collection_id}/all", {"X-Plex-Container-Size": limit}
        else:
            path, params = "/library/recentlyAdded", {"X-Plex-Container-Size": limit}
        client = self._client_for_server(server)
        payload = await client.request(server, path, params=params)
        raw_items = client.metadata(payload)
        if not raw_items:
            for hub_entry in client.media_container(payload).get("Hub", []):
                if isinstance(hub_entry, dict):
                    raw_items.extend(item for item in hub_entry.get("Metadata", []) if isinstance(item, dict))
        return [normalize_item(item, config_id=config_id, server=server) for item in raw_items[:limit]]

    async def resolve(self, instance_id: str, item_id: str) -> dict[str, Any]:
        config_id, server = self.resolve_server(instance_id)
        client = self._client_for_server(server)
        payload = await client.request(server, f"/library/metadata/{item_id}")
        items = client.metadata(payload)
        if not items:
            raise HTTPException(status_code=404, detail="Plex media item not found")
        return normalize_item(items[0], config_id=config_id, server=server)

    async def action(self, instance_id: str, action: str, *, item_id: str = "", value: Any = None, collection_id: str = "") -> dict[str, Any]:
        _config_id, server = self.resolve_server(instance_id)
        if action == "mark_watched":
            path, params = "/:/scrobble", {"key": item_id, "identifier": "com.plexapp.plugins.library"}
        elif action == "mark_unwatched":
            path, params = "/:/unscrobble", {"key": item_id, "identifier": "com.plexapp.plugins.library"}
        elif action == "rate":
            path, params = "/:/rate", {"key": item_id, "rating": value, "identifier": "com.plexapp.plugins.library"}
        elif action == "scan_library":
            path, params = f"/library/sections/{collection_id}/refresh", {}
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported Plex action: {action}")
        if action != "scan_library" and not item_id:
            raise HTTPException(status_code=422, detail="item_id is required")
        await self._client_for_server(server).request(server, path, params=params)
        return {"ok": True, "action": action, "provider_instance_id": instance_id, "item_id": item_id, "collection_id": collection_id}

    async def asset(self, instance_id: str, path: str) -> tuple[bytes, str]:
        _config_id, server = self.resolve_server(instance_id)
        if not path.startswith("/") or ".." in path or "\\" in path:
            raise HTTPException(status_code=400, detail="Invalid Plex asset path")
        return await self._client_for_server(server).bytes(server, path)

    def _client_for_server(self, server: PlexServer):
        return self.simulator_client if server.base_url.startswith("simulator://") else self.client

    @staticmethod
    def _public_server(config_id: str, server: PlexServer) -> dict[str, Any]:
        return {
            "id": f"{config_id}:{server.machine_id}", "provider": "plex",
            "config_id": config_id, "machine_id": server.machine_id, "name": server.name,
            "owned": server.owned, "local": server.local, "relay": server.relay,
            "capabilities": ["browse", "search", "collections", "recently_added", "on_deck", "playback"],
        }

    @staticmethod
    def _first_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}
