from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from piphi_runtime_testkit_python import build_config_payload, build_runtime_headers

from piphi_android_adb_sidecar import state
from piphi_android_adb_sidecar.main import app
from piphi_android_adb_sidecar.transport import BoundedQueue

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text())


class ConformanceSession:
    def __init__(self, config) -> None:
        self.queue = BoundedQueue(config.queue_capacity)
        self.connected = False
        self.authorized = False
        self.target_id: str | None = None
        self.metadata: dict[str, str] = {}

    async def open(self) -> None:
        self.connected = True
        self.authorized = True
        self.target_id = "adb-conformance-target"

    async def close(self) -> None:
        self.connected = False
        self.authorized = False


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_headers = {"Authorization": "Bearer test-internal-token"}
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "test-internal-token")
    monkeypatch.setattr(state, "session_factory", ConformanceSession)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            for fixture in FIXTURES["cases"]:
                payload = fixture.get("body")
                headers = token_headers
                if fixture["id"] == "config":
                    payload = build_config_payload(
                        config_id=str(payload.get("id", "demo-device")),
                        extra=payload,
                    )
                    headers = {**build_runtime_headers(), **token_headers}
                response = await client.request(
                    fixture["method"],
                    fixture["path"],
                    json=payload,
                    headers=headers,
                )
                assert response.status_code == fixture["status"], fixture["id"]
                body = response.json()
                _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
                _assert_required_any_keys(
                    body,
                    fixture.get("required_any_keys", []),
                    fixture["id"],
                )
        finally:
            await client.post(
                "/deconfigure/demo-device",
                headers=token_headers,
            )


def _assert_required_keys(body: dict[str, Any], keys: list[str], fixture_id: str) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(body: dict[str, Any], groups: list[list[str]], fixture_id: str) -> None:
    for group in groups:
        assert any(key in body for key in group), f"{fixture_id} missing one of {', '.join(group)}"
