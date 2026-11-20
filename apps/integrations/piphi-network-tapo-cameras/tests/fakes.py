from __future__ import annotations

from copy import deepcopy
from typing import Any


def camera_snapshot(**updates: Any) -> dict[str, Any]:
    snapshot = {
        "hardware_id": "opaque-hardware-id",
        "name": "Fixture camera",
        "model": "Fixture C100",
        "hardware": "1.0",
        "firmware": "1.2.3",
        "device_type": "camera",
        "privacy_mode": False,
        "signal_strength": -51,
        "connected": True,
    }
    snapshot.update(updates)
    return snapshot


class FakeTapoClient:
    def __init__(self, *outcomes: dict[str, Any] | Exception) -> None:
        self.outcomes = list(outcomes or [camera_snapshot()])
        self.closed = False
        self.refresh_count = 0

    async def refresh(self) -> dict[str, Any]:
        self.refresh_count += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return deepcopy(outcome)

    async def close(self) -> None:
        self.closed = True
