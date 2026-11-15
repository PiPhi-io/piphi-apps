from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from piphi_network_modbus.main import app
from piphi_network_modbus.state import runtime

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text()
)


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        try:
            for fixture in FIXTURES["cases"]:
                response = await client.request(
                    fixture["method"],
                    fixture["path"],
                    json=fixture.get("body"),
                )
                assert response.status_code == fixture["status"], fixture["id"]
                body = response.json()
                _assert_required_keys(
                    body, fixture.get("required_keys", []), fixture["id"]
                )
                _assert_required_any_keys(
                    body, fixture.get("required_any_keys", []), fixture["id"]
                )
        finally:
            await client.post("/deconfigure/demo-device")


def _assert_required_keys(
    body: dict[str, Any], keys: list[str], fixture_id: str
) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(
    body: dict[str, Any], groups: list[list[str]], fixture_id: str
) -> None:
    for group in groups:
        assert any(key in body for key in group), (
            f"{fixture_id} missing one of {', '.join(group)}"
        )


@pytest.mark.anyio
async def test_operational_routes_require_runtime_identity() -> None:
    runtime.auth.container_id = "secured-container"
    runtime.auth.internal_token = "secured-token"
    headers = {
        "X-Container-Id": "secured-container",
        "X-PiPhi-Integration-Token": "secured-token",
    }
    routes = [
        ("GET", "/state"),
        ("GET", "/entities"),
        ("GET", "/events"),
        ("GET", "/diagnostics"),
        ("GET", "/contract"),
        ("GET", "/ui-config"),
        ("POST", "/events/example"),
        ("POST", "/telemetry/example"),
        ("POST", "/discover"),
    ]
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            assert (await client.get("/health")).status_code == 200
            for method, path in routes:
                denied = await client.request(method, path, json={})
                accepted = await client.request(method, path, json={}, headers=headers)
                assert denied.status_code == 401, path
                assert accepted.status_code != 401, path
    finally:
        runtime.auth.container_id = ""
        runtime.auth.internal_token = ""
