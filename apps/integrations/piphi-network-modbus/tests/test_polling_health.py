from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from piphi_network_modbus import state
from piphi_network_modbus.profile_codec import point_metadata
from piphi_network_modbus.schemas import DeviceConfig


def polling_config() -> DeviceConfig:
    return DeviceConfig.model_validate(
        {
            "id": "polling-health",
            "host": "127.0.0.1",
            "poll_interval_seconds": 0,
            "poll_jitter_percent": 0,
            "poll_backoff_max_seconds": 60,
            "points": [
                {"id": "fast", "name": "Fast", "unit_id": 1, "address": 0},
                {"id": "manual", "name": "Manual", "unit_id": 2, "address": 0},
            ],
            "poll_groups": [
                {
                    "id": "priority",
                    "point_ids": ["fast"],
                    "interval_seconds": 10,
                    "priority": 10,
                },
                {
                    "id": "disabled",
                    "point_ids": ["manual"],
                    "interval_seconds": 0,
                },
            ],
        }
    )


class PollingClient:
    def __init__(self) -> None:
        self.failed = False
        self.snapshots: list[list[str]] = []

    async def snapshot(self, points) -> dict[str, Any]:
        self.snapshots.append([point.id for point in points])
        now = datetime.now(UTC).isoformat()
        return {
            "connected": not self.failed,
            "responsive_unit_ids": [] if self.failed else sorted({point.unit_id for point in points}),
            "request_count": len(points),
            "request_success_count": 0 if self.failed else len(points),
            "request_failure_count": len(points) if self.failed else 0,
            "poll_duration_ms": 2.5,
            "retry_count": 0,
            "timeout_count": int(self.failed),
            "error_count": 0,
            "reconnect_count": 0,
            "last_error_code": "timeout" if self.failed else None,
            "unit_health": [],
            "points": [
                {
                    **point_metadata(point),
                    "value": None if self.failed else point.unit_id,
                    "quality": "unavailable" if self.failed else "good",
                    "updated_at": None if self.failed else now,
                    "error_code": "timeout" if self.failed else None,
                }
                for point in points
            ],
        }

    async def close(self) -> None:
        return None


def test_poll_groups_reject_unknown_or_duplicate_points() -> None:
    payload = polling_config().model_dump()
    payload["poll_groups"][0]["point_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown points"):
        DeviceConfig.model_validate(payload)

    payload = polling_config().model_dump()
    payload["poll_groups"][1]["point_ids"] = ["fast"]
    with pytest.raises(ValidationError, match="only one poll group"):
        DeviceConfig.model_validate(payload)


@pytest.mark.anyio
async def test_disabled_polling_backoff_metrics_and_transition_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PollingClient()
    monkeypatch.setattr(state, "tcp_client_factory", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = polling_config()
    await state.apply_config(config)
    entry = state.registry.get(config.id)
    assert entry is not None
    event_start = len(state.registry.recent_events)
    state.initialize_poll_schedule(entry, config, now=100)
    try:
        schedule = entry["poll_schedule"]
        assert schedule["disabled"]["next_poll_at"] is None
        assert schedule["priority"]["next_poll_at"] == 110

        await state.poll_due_groups(now=110)
        assert client.snapshots[-1] == ["fast"]
        assert schedule["priority"]["next_poll_at"] == 120

        client.failed = True
        await state.poll_due_groups(now=120)
        assert schedule["priority"]["consecutive_failures"] == 1
        assert schedule["priority"]["next_poll_at"] == 140
        assert entry["poll_metrics"]["poll_failure_count"] == 1
        assert entry["poll_health"] == "degraded"

        client.failed = False
        await state.poll_due_groups(now=140)
        assert schedule["priority"]["consecutive_failures"] == 0
        assert schedule["priority"]["next_poll_at"] == 150
        events = [
            event["event_type"] for event in state.registry.recent_events[event_start:]
        ]
        assert events.count("transport.degraded") == 1
        assert events.count("transport.recovered") == 1
        assert events.count("points.stale") == 1
        assert events.count("points.recovered") == 1

        diagnostics = state.polling_diagnostics()[config.id]
        assert diagnostics["poll_health"] == "healthy"
        assert {group["id"]: group["enabled"] for group in diagnostics["groups"]} == {
            "disabled": False,
            "priority": True,
        }
    finally:
        await state.remove_config(config.id)
