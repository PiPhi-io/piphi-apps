from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from datetime import UTC, datetime

from conftest import RUNTIME_HEADERS
from piphi_network_kaiterra_api import state
from piphi_network_kaiterra_api.kaiterra import KaiterraDeviceMetadata, KaiterraReading
from piphi_network_kaiterra_api.main import app


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text())


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures() -> None:
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def latest_reading(self, _udid):
            now = datetime.now(UTC)
            return KaiterraReading(
                metrics={"co2_ppm": 500, "connected": True},
                units={"co2_ppm": "ppm"}, latest_timestamp=now.isoformat(),
                latency_ms=1, observed_at=now,
            )

        async def device_metadata(self, _udid):
            return KaiterraDeviceMetadata("Office", "SE-100", "1.0")

        async def close(self):
            return None

    state.runtime_data.client_factory = FakeClient
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for fixture in FIXTURES["cases"]:
            response = await client.request(
                fixture["method"],
                fixture["path"],
                json=fixture.get("body"),
                headers={} if fixture["path"] == "/health" else RUNTIME_HEADERS,
            )
            assert response.status_code == fixture["status"], fixture["id"]
            body = response.json()
            _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
            _assert_required_any_keys(body, fixture.get("required_any_keys", []), fixture["id"])
    await state.remove_config("kaiterra-sensedge")


def _assert_required_keys(body: dict[str, Any], keys: list[str], fixture_id: str) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(body: dict[str, Any], groups: list[list[str]], fixture_id: str) -> None:
    for group in groups:
        assert any(key in body for key in group), f"{fixture_id} missing one of {', '.join(group)}"
