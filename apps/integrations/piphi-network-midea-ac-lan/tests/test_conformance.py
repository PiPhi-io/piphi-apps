from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from piphi_network_midea_ac_lan.main import app
from piphi_network_midea_ac_lan import state


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text())


@pytest.fixture(autouse=True)
def fake_midea_client(monkeypatch):
    class Client:
        async def refresh(self):
            return {
                "connected": True,
                "power": True,
                "hvac_mode": "cool",
                "target_temperature_c": 22.0,
                "indoor_temperature_c": 24.0,
            }

    async def connect(**kwargs):
        return Client()

    monkeypatch.setattr(state, "_client_connector", connect)


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for fixture in FIXTURES["cases"]:
            response = await client.request(
                fixture["method"],
                fixture["path"],
                json=fixture.get("body"),
            )
            assert response.status_code == fixture["status"], fixture["id"]
            body = response.json()
            _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
            _assert_required_any_keys(body, fixture.get("required_any_keys", []), fixture["id"])


def _assert_required_keys(body: dict[str, Any], keys: list[str], fixture_id: str) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(body: dict[str, Any], groups: list[list[str]], fixture_id: str) -> None:
    for group in groups:
        assert any(key in body for key in group), f"{fixture_id} missing one of {', '.join(group)}"
