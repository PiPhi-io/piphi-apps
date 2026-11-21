from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from piphi_runtime_kit_python import schedule_event_delivery, schedule_telemetry_delivery

from .plex_client import PlexClient, PlexServer, normalize_collection, normalize_item
from .schemas import DeviceConfig
from .simulator import SimulatedPlexClient


@dataclass(slots=True)
class PlexConnection:
    config: DeviceConfig
    entry: dict[str, Any]
    servers: dict[str, PlexServer] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failure_reason: str | None = None
    consecutive_failures: int = 0


class PlexRuntimeService:
    def __init__(self, *, registry, runtime, telemetry, events, client: PlexClient | None = None):
        self.registry = registry
        self.runtime = runtime
        self.telemetry = telemetry
        self.events = events
        self.client = client or PlexClient()
        self.simulator_client = SimulatedPlexClient()
        self.connections: dict[str, PlexConnection] = {}
        self._lock = asyncio.Lock()

    async def configure(self, config: DeviceConfig, entry: dict[str, Any]) -> None:
        config_id = str(entry["config_id"])
        connection = PlexConnection(config=config, entry=entry)
        await self._discover(connection)
        async with self._lock:
            await self._remove_locked(config_id)
            self.connections[config_id] = connection
            self.registry.set(config_id, entry)
            await self._publish(connection)
            connection.task = asyncio.create_task(
                self._poll(connection), name=f"plex-poll-{config_id}"
            )

    async def refresh(self, config_id: str) -> dict[str, Any]:
        connection = self.connections.get(config_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Unknown Plex configuration")
        async with connection.refresh_lock:
            try:
                await self._discover(connection)
            except (httpx.HTTPError, ValueError, HTTPException):
                connection.consecutive_failures += 1
                connection.failure_reason = "provider_unavailable"
                previous = self.registry.state_snapshots.get(config_id, {}).get("state", {})
                state = {
                    **previous,
                    "connected": False,
                    "available": False,
                    "stale": bool(previous.get("last_success_at")),
                    "failure_reason": connection.failure_reason,
                    "consecutive_failures": connection.consecutive_failures,
                }
                self.registry.update_state(
                    config_id, state, device_id=str(connection.entry["device_id"])
                )
                if connection.consecutive_failures == 1 and previous.get("last_success_at"):
                    self._emit(
                        connection,
                        "plex.server.unavailable",
                        {"reason": connection.failure_reason},
                        severity="warning",
                    )
                return state
            return await self._publish(connection)

    async def _discover(self, connection: PlexConnection) -> None:
        client = self.simulator_client if connection.config.simulation_mode else self.client
        discovered = await client.discover(
            connection.config.token.get_secret_value(),
            base_url=connection.config.base_url,
            host=connection.config.host,
            include_remote=connection.config.include_remote_servers,
        )
        if not discovered:
            raise HTTPException(status_code=502, detail="No Plex servers were discovered")
        connection.servers = {server.machine_id: server for server in discovered}

    async def _publish(self, connection: PlexConnection) -> dict[str, Any]:
        config_id = str(connection.entry["config_id"])
        previous = self.registry.state_snapshots.get(config_id, {}).get("state")
        sessions: list[dict[str, Any]] = []
        for server in connection.servers.values():
            try:
                client = self._client_for_server(server)
                payload = await client.request(server, "/status/sessions")
                for session in client.metadata(payload):
                    user = self._first_mapping(session.get("User"))
                    player = self._first_mapping(session.get("Player"))
                    sessions.append(
                        {
                            "server_id": server.machine_id,
                            "session_id": str(
                                session.get("sessionKey") or session.get("ratingKey") or ""
                            ),
                            "title": str(
                                session.get("title") or session.get("grandparentTitle") or "Unknown"
                            ),
                            "kind": str(session.get("type") or "unknown"),
                            "user": str(user.get("title") or session.get("user") or ""),
                            "player": str(player.get("title") or ""),
                            "state": str(player.get("state") or ""),
                            "transcode": bool(session.get("TranscodeSession")),
                        }
                    )
            except (httpx.HTTPError, ValueError, HTTPException):
                continue
        state = {
            "connected": bool(connection.servers),
            "available": True,
            "stale": False,
            "server_count": len(connection.servers),
            "active_sessions": len(sessions),
            "transcode_sessions": sum(1 for session in sessions if session["transcode"]),
            "servers": [
                self._public_server(config_id, server) for server in connection.servers.values()
            ],
            "last_success_at": datetime.now(UTC).isoformat(),
            "failure_reason": None,
            "consecutive_failures": 0,
        }
        connection.failure_reason = None
        connection.consecutive_failures = 0
        self.registry.update_state(config_id, state, device_id=str(connection.entry["device_id"]))
        if previous is not None:
            if previous.get("available") is False:
                self._emit(connection, "plex.server.recovered")
            if previous.get("active_sessions") != state["active_sessions"]:
                self._emit(
                    connection,
                    "plex.sessions.changed",
                    {"from": previous.get("active_sessions"), "to": state["active_sessions"]},
                )
        schedule_telemetry_delivery(
            process_state=self.runtime.process_state,
            telemetry_client=self.telemetry,
            auth_context=self.runtime.auth,
            config_id=config_id,
            device_id=str(connection.entry["device_id"]),
            container_id=connection.entry.get("container_id"),
            metrics={
                key: state[key]
                for key in (
                    "connected",
                    "available",
                    "stale",
                    "server_count",
                    "active_sessions",
                    "transcode_sessions",
                    "consecutive_failures",
                )
            },
            units={
                "server_count": "servers",
                "active_sessions": "sessions",
                "transcode_sessions": "sessions",
            },
        )
        return state

    def _emit(
        self,
        connection: PlexConnection,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        severity: str = "info",
    ) -> None:
        schedule_event_delivery(
            process_state=self.runtime.process_state,
            event_client=self.events,
            auth_context=self.runtime.auth,
            event_type=event_type,
            device=connection.entry,
            payload=payload or {},
            source="piphi-network-plex",
            severity=severity,
            record_event=self.registry.append_event,
        )

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
            values.extend(
                self._public_server(current_id, server) for server in connection.servers.values()
            )
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
        return [
            normalize_collection(item, config_id=config_id, server=server)
            for item in client.metadata(payload)
        ]

    async def items(
        self,
        instance_id: str,
        *,
        collection_id: str = "",
        hub: str = "",
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
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
            path, params = (
                f"/library/sections/{collection_id}/all",
                {"X-Plex-Container-Size": limit},
            )
        else:
            path, params = "/library/recentlyAdded", {"X-Plex-Container-Size": limit}
        client = self._client_for_server(server)
        payload = await client.request(server, path, params=params)
        raw_items = client.metadata(payload)
        if not raw_items:
            for hub_entry in client.media_container(payload).get("Hub", []):
                if isinstance(hub_entry, dict):
                    raw_items.extend(
                        item for item in hub_entry.get("Metadata", []) if isinstance(item, dict)
                    )
        return [
            normalize_item(item, config_id=config_id, server=server) for item in raw_items[:limit]
        ]

    async def resolve(self, instance_id: str, item_id: str) -> dict[str, Any]:
        config_id, server = self.resolve_server(instance_id)
        client = self._client_for_server(server)
        payload = await client.request(server, f"/library/metadata/{item_id}")
        items = client.metadata(payload)
        if not items:
            raise HTTPException(status_code=404, detail="Plex media item not found")
        return normalize_item(items[0], config_id=config_id, server=server)

    async def action(
        self,
        instance_id: str,
        action: str,
        *,
        item_id: str = "",
        value: Any = None,
        collection_id: str = "",
    ) -> dict[str, Any]:
        config_id, server = self.resolve_server(instance_id)
        connection = self.connections[config_id]
        if not connection.config.allow_mutating_actions:
            raise HTTPException(
                status_code=403,
                detail="Plex mutating actions are disabled for this configuration",
            )
        safe_id = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
        if item_id and not safe_id.fullmatch(item_id):
            raise HTTPException(status_code=422, detail="Invalid Plex item identifier")
        if collection_id and not safe_id.fullmatch(collection_id):
            raise HTTPException(status_code=422, detail="Invalid Plex collection identifier")
        path: str
        params: dict[str, Any]
        if action == "mark_watched":
            path, params = (
                "/:/scrobble",
                {"key": item_id, "identifier": "com.plexapp.plugins.library"},
            )
        elif action == "mark_unwatched":
            path, params = (
                "/:/unscrobble",
                {"key": item_id, "identifier": "com.plexapp.plugins.library"},
            )
        elif action == "rate":
            try:
                rating = float(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422, detail="Rating must be between 0 and 10"
                ) from exc
            if not 0 <= rating <= 10:
                raise HTTPException(status_code=422, detail="Rating must be between 0 and 10")
            path, params = (
                "/:/rate",
                {"key": item_id, "rating": rating, "identifier": "com.plexapp.plugins.library"},
            )
        elif action == "scan_library":
            path, params = f"/library/sections/{collection_id}/refresh", {}
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported Plex action: {action}")
        if action != "scan_library" and not item_id:
            raise HTTPException(status_code=422, detail="item_id is required")
        await self._client_for_server(server).request(server, path, params=params)
        return {
            "ok": True,
            "action": action,
            "provider_instance_id": instance_id,
            "item_id": item_id,
            "collection_id": collection_id,
        }

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
            "id": f"{config_id}:{server.machine_id}",
            "provider": "plex",
            "config_id": config_id,
            "machine_id": server.machine_id,
            "name": server.name,
            "owned": server.owned,
            "local": server.local,
            "relay": server.relay,
            "capabilities": [
                "browse",
                "search",
                "collections",
                "recently_added",
                "on_deck",
                "playback",
            ],
        }

    @staticmethod
    def _first_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
        return {}
