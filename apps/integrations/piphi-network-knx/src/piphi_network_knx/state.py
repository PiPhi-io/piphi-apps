from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .protocol import KnxClient, XknxClient
from .schemas import DatapointConfig, DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
automations = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(
        os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")
    )
)

capabilities = CAPABILITIES
commands = COMMANDS
ClientFactory = Callable[
    [DeviceConfig, Callable[[str, Any], None], Callable[[bool], None]], KnxClient
]


@dataclass(slots=True)
class Session:
    config: DeviceConfig
    entry: dict[str, Any]
    client: KnxClient
    values: dict[str, Any] = field(default_factory=dict)
    updated_at: dict[str, str] = field(default_factory=dict)


class KnxSessionManager:
    def __init__(self, client_factory: ClientFactory = XknxClient) -> None:
        self.client_factory = client_factory
        self.sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self.persistence_path = Path(os.getenv("PIPHI_KNX_CONFIG_PATH", "./data/knx-configs.json"))

    async def apply(self, config: DeviceConfig, *, persist: bool = True) -> None:
        duplicate = next(
            (
                session
                for config_id, session in self.sessions.items()
                if config_id != config.id
                and session.config.host == config.host
                and session.config.port == config.port
            ),
            None,
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail="this KNX/IP endpoint is already owned by another configuration",
            )
        entry = make_entry(config)
        client = self.client_factory(
            config,
            lambda datapoint_id, value: self._value_received(config.id, datapoint_id, value),
            lambda connected: self._connection_changed(config.id, connected),
        )
        try:
            await client.start()
        except Exception as exc:
            await client.stop()
            raise HTTPException(
                status_code=422,
                detail={"error": "knx_connection_failed", "message": str(exc)},
            ) from exc

        candidate = Session(config=config, entry=entry, client=client)
        old_session: Session | None
        async with self._lock:
            old_session = self.sessions.get(config.id)
            self.sessions[config.id] = candidate
            registry.set(config.id, entry)
            self._publish_state(candidate)
        if old_session is not None:
            await old_session.client.stop()
        append_runtime_event(
            "gateway.online",
            entry,
            {"transport": config.transport, "datapoint_count": len(config.datapoints)},
        )
        for datapoint in config.datapoints:
            if datapoint.read_on_init:
                try:
                    await client.read(datapoint)
                except Exception as exc:
                    append_runtime_event(
                        "datapoint.read_failed",
                        entry,
                        {"datapoint_id": datapoint.id, "error": type(exc).__name__},
                        severity="warning",
                    )
        if persist:
            self._persist()

    async def remove(self, config_id: str, *, persist: bool = True) -> bool:
        async with self._lock:
            session = self.sessions.pop(config_id, None)
            entry = registry.remove(config_id)
        if session is None:
            return False
        await session.client.stop()
        append_runtime_event("runtime.config.removed", entry or session.entry)
        if persist:
            self._persist()
        return True

    async def stop_all(self) -> None:
        sessions = list(self.sessions.values())
        self.sessions.clear()
        await asyncio.gather(*(item.client.stop() for item in sessions), return_exceptions=True)

    async def restore(self) -> None:
        if not self.persistence_path.exists():
            return
        try:
            payload = json.loads(self.persistence_path.read_text(encoding="utf-8"))
            configs = [DeviceConfig.model_validate(item) for item in payload.get("configs", [])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return
        for config in configs:
            try:
                await self.apply(config, persist=False)
            except HTTPException:
                continue

    def get(self, config_id: str) -> Session:
        session = self.sessions.get(config_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
        return session

    async def read(self, config_id: str, datapoint_id: str) -> dict[str, Any]:
        session = self.get(config_id)
        datapoint = self._datapoint(session, datapoint_id)
        await session.client.read(datapoint)
        return {"accepted": True, "datapoint_id": datapoint_id}

    async def write(self, config_id: str, datapoint_id: str, value: Any) -> dict[str, Any]:
        session = self.get(config_id)
        datapoint = self._datapoint(session, datapoint_id)
        if not session.config.allow_writes or not datapoint.writable:
            raise HTTPException(status_code=403, detail="datapoint is not write-allowlisted")
        try:
            await session.client.write(datapoint, value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (ConnectionError, RuntimeError, TimeoutError) as exc:
            append_runtime_event(
                "telegram.write_failed",
                session.entry,
                {"datapoint_id": datapoint.id, "outcome": "unknown"},
                severity="warning",
            )
            raise HTTPException(
                status_code=503,
                detail={"error": "write_outcome_unknown", "message": str(exc)},
            ) from exc
        append_runtime_event(
            "telegram.write_accepted",
            session.entry,
            {"datapoint_id": datapoint.id, "feedback_pending": True},
        )
        return {
            "accepted": True,
            "datapoint_id": datapoint.id,
            "feedback_pending": True,
        }

    def entities(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for session in self.sessions.values():
            for datapoint in session.config.datapoints:
                command_ids = ["read_datapoint"]
                if datapoint.writable and session.config.allow_writes:
                    command_ids.append("write_datapoint")
                quality = self._quality(session, datapoint)
                result.append(
                    {
                        "id": f"{session.entry['device_id']}:{datapoint.id}",
                        "name": datapoint.name,
                        "config_id": session.entry["config_id"],
                        "device_id": session.entry["device_id"],
                        "entity_type": datapoint.entity_type,
                        "capabilities": ["connected", "datapoint_value", *command_ids],
                        "available_commands": [
                            {"id": item, "label": item.replace("_", " ").title(), "kind": "action"}
                            for item in command_ids
                        ],
                        "state": {
                            "value": session.values.get(datapoint.id),
                            "quality": quality,
                            "updated_at": session.updated_at.get(datapoint.id),
                            "dpt": datapoint.dpt,
                            "unit": _unit_for(datapoint),
                        },
                    }
                )
        return result

    def _quality(self, session: Session, datapoint: DatapointConfig) -> str:
        updated_at = session.updated_at.get(datapoint.id)
        if updated_at is None:
            return "uninitialized"
        age = datetime.now(UTC) - datetime.fromisoformat(updated_at)
        if age.total_seconds() > datapoint.stale_after_seconds:
            return "stale"
        return "fresh"

    def diagnostics(self) -> dict[str, Any]:
        return {
            "sessions": [
                {
                    "config_id": session.entry["config_id"],
                    "connected": session.client.connected,
                    "transport": session.config.transport,
                    "datapoint_count": len(session.config.datapoints),
                    "initialized_datapoints": len(session.values),
                    "writes_enabled": session.config.allow_writes,
                }
                for session in self.sessions.values()
            ]
        }

    def health_summary(self) -> dict[str, Any]:
        datapoints = [
            (session, datapoint)
            for session in self.sessions.values()
            for datapoint in session.config.datapoints
        ]
        qualities = [self._quality(session, datapoint) for session, datapoint in datapoints]
        return {
            "session_count": len(self.sessions),
            "connected_session_count": sum(
                1 for session in self.sessions.values() if session.client.connected
            ),
            "uninitialized_datapoint_count": qualities.count("uninitialized"),
            "stale_datapoint_count": qualities.count("stale"),
        }

    def _datapoint(self, session: Session, datapoint_id: str) -> DatapointConfig:
        datapoint = next(
            (item for item in session.config.datapoints if item.id == datapoint_id), None
        )
        if datapoint is None:
            raise HTTPException(status_code=404, detail=f"unknown datapoint_id={datapoint_id}")
        return datapoint

    def _value_received(self, config_id: str, datapoint_id: str, value: Any) -> None:
        session = self.sessions.get(config_id)
        if session is None:
            return
        previous = session.values.get(datapoint_id)
        session.values[datapoint_id] = value
        session.updated_at[datapoint_id] = datetime.now(UTC).isoformat()
        self._publish_state(session)
        if previous is not None and previous != value:
            append_runtime_event(
                "datapoint.changed",
                session.entry,
                {"datapoint_id": datapoint_id, "value": value},
            )

    def _connection_changed(self, config_id: str, connected: bool) -> None:
        session = self.sessions.get(config_id)
        if session is None:
            return
        self._publish_state(session)
        append_runtime_event(
            "gateway.online" if connected else "gateway.offline",
            session.entry,
        )

    def _publish_state(self, session: Session) -> None:
        registry.update_state(
            session.config.id,
            {
                "connected": session.client.connected,
                "transport": session.config.transport,
                "datapoints": session.values.copy(),
                "updated_at": session.updated_at.copy(),
                "config_id": session.entry["config_id"],
            },
            device_id=session.entry["device_id"],
        )

    def _persist(self) -> None:
        self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.persistence_path.with_suffix(".tmp")
        payload = {
            "schema_version": 1,
            "configs": [
                session.config.model_dump(mode="json") for session in self.sessions.values()
            ],
        }
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(self.persistence_path)


def _unit_for(datapoint: DatapointConfig) -> str | None:
    return {"5.001": "%", "9.001": "°C"}.get(str(datapoint.dpt))


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "alias": config.alias,
        "config": config.model_dump(mode="json", exclude={"host", "local_ip"}),
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    *,
    severity: str = "info",
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity=severity,
    )
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


manager = KnxSessionManager()


async def apply_config(config: DeviceConfig) -> None:
    await manager.apply(config)


async def remove_config(config_id: str) -> bool:
    return await manager.remove(config_id)


def _register_automation_actions() -> None:
    async def read_handler(request: Any) -> dict[str, Any]:
        target = request.target if isinstance(request.target, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        datapoint_id = str(request.args.get("datapoint_id") or request.entity_id or "")
        return await manager.read(config_id, datapoint_id)

    async def write_handler(request: Any) -> dict[str, Any]:
        target = request.target if isinstance(request.target, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        datapoint_id = str(request.args.get("datapoint_id") or request.entity_id or "")
        if "value" not in request.args:
            raise HTTPException(status_code=422, detail="value is required")
        return await manager.write(config_id, datapoint_id, request.args["value"])

    automations.action("read_datapoint", label="Read datapoint")(read_handler)
    automations.action("write_datapoint", label="Write datapoint")(write_handler)


_register_automation_actions()
