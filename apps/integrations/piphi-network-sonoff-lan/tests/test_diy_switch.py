from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_sonoff_lan import state
from piphi_network_sonoff_lan.diy import diy_origin, read_switch_state
from piphi_network_sonoff_lan.main import app
from piphi_network_sonoff_lan.schemas import DeviceConfig


@pytest.mark.anyio
async def test_reads_actual_switch_state_from_documented_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"seq": 1, "error": 0, "data": {"switch": "on"}}
        )

    state_on = await read_switch_state(
        "127.0.0.1:8081", "100000140e", transport=httpx.MockTransport(handle)
    )
    assert state_on is True
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "http://127.0.0.1:8081/zeroconf/info"
    assert json.loads(requests[0].content) == {"deviceid": "100000140e", "data": {}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"error": 401, "data": {"switch": "on"}},
        {"error": 0, "data": {"switches": [{"switch": "on"}]}},
        {"error": 0, "data": {"switch": "unknown"}},
    ],
)
async def test_rejects_encrypted_multi_channel_and_invalid_responses(
    payload: dict,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await read_switch_state("127.0.0.1", "100000140e", transport=transport)


@pytest.mark.parametrize(
    "host", ["example.com", "8.8.8.8", "127.0.0.1/path", "user@127.0.0.1"]
)
def test_nonlocal_or_ambiguous_hosts_rejected(host: str) -> None:
    with pytest.raises(ValueError):
        diy_origin(host)


@pytest.mark.anyio
async def test_invalid_device_id_never_sends_request() -> None:
    transport = httpx.MockTransport(
        lambda _request: (_ for _ in ()).throw(AssertionError)
    )
    with pytest.raises(ValueError, match="device ID"):
        await read_switch_state("127.0.0.1", "bad id", transport=transport)


@pytest.mark.anyio
async def test_runtime_publishes_actual_state_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = state.make_entry(
        DeviceConfig(id="sonoff-diy-test", host="127.0.0.1", diy_device_id="100000140e")
    )
    state.registry.set(entry["config_id"], entry)

    async def successful_read(_host: str, _device_id: str) -> bool:
        return False

    monkeypatch.setattr(state, "read_switch_state", successful_read)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    try:
        assert await state.refresh_entry(entry) == {
            "connected": True,
            "switch_on": False,
        }

        async def failed_read(_host: str, _device_id: str) -> bool:
            raise ValueError("encrypted")

        monkeypatch.setattr(state, "read_switch_state", failed_read)
        assert await state.refresh_entry(entry) == {
            "connected": False,
            "reason": "diy_info_failed",
        }
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_unconfigured_runtime_has_no_demo_entity() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        assert all(
            item["id"] != "demo-device"
            for item in (await client.get("/entities")).json()["entities"]
        )
        assert not (await client.post("/discover", json={})).json().get("devices")


@pytest.mark.anyio
async def test_configuration_requires_diy_device_id() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/config", json={"id": "missing-diy-id", "host": "127.0.0.1"}
        )
    assert response.status_code == 422


def test_widget_is_read_only_and_bound_to_switch_state() -> None:
    root = Path(__file__).parents[1]
    package = json.loads(
        (root / "experiences/diy_switch/package.source.json").read_text()
    )
    widget = package["widgets"][0]
    assert widget["runtime"] == "declarative"
    assert widget["binding_slots"][0]["capability_requirements"] == ["switch_on"]
    assert widget["binding_slots"][0]["binding_modes"] == ["read"]
