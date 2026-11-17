from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from piphi_camera_stream.main import app
from piphi_camera_stream.source_probe import SourceProbeResult

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text()
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    ["/entities", "/state", "/diagnostics", "/contract", "/ui-config", "/events"],
)
async def test_operational_routes_fail_closed_without_runtime_identity(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    assert response.status_code == 503


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(True, "available")),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        for fixture in FIXTURES["cases"]:
            response = await client.request(
                fixture["method"],
                fixture["path"],
                json=fixture.get("body"),
            )
            assert response.status_code == fixture["status"], fixture["id"]
            body = response.json()
            _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
            _assert_required_any_keys(
                body, fixture.get("required_any_keys", []), fixture["id"]
            )


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
