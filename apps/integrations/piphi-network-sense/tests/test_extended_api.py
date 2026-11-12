from __future__ import annotations

import json
from pathlib import Path

import pytest

from piphi_network_sense.extended_api import SenseExtendedApi


@pytest.fixture
def responses() -> dict:
    path = Path(__file__).parent / "fixtures" / "sense-extended-api.json"
    return json.loads(path.read_text())


@pytest.mark.anyio
async def test_extended_api_normalizes_read_only_responses(responses) -> None:
    calls = []

    async def api_call(endpoint, payload):
        calls.append((endpoint, payload))
        if endpoint.endswith("/devices"):
            return responses["devices"]
        if endpoint.endswith("/always_on"):
            return responses["always_on"]
        if endpoint.endswith("/unknown"):
            return responses["unknown"]
        if endpoint.endswith("/timeline"):
            return responses["timeline"]
        raise AssertionError(endpoint)

    api = SenseExtendedApi(api_call, monitor_id="monitor-1", user_id="user-1")
    snapshot = await api.refresh(timeline_items=500)

    assert snapshot.always_on_power_w == 312.4
    assert snapshot.other_power_w == 187.6
    assert snapshot.appliances[0].device_type == "Microwave"
    assert snapshot.appliances[0].first_usage == "2025-01-12"
    assert snapshot.appliances[0].timeline_enabled is True
    assert snapshot.appliances[1].timeline_enabled is False
    assert snapshot.timeline_events[0].body == "Microwave turned on"
    assert snapshot.timeline_events[0].device_id == "microwave-1"
    assert snapshot.timeline_events[1].subtype == "NewDeviceFound"
    assert calls[-1] == ("users/user-1/timeline", {"n_items": 100})


@pytest.mark.anyio
async def test_extended_api_preserves_last_good_values_after_endpoint_failure(responses) -> None:
    failing = False

    async def api_call(endpoint, _payload):
        if failing:
            raise RuntimeError("private endpoint moved")
        if endpoint.endswith("/devices"):
            return responses["devices"]
        if endpoint.endswith("/always_on"):
            return responses["always_on"]
        if endpoint.endswith("/unknown"):
            return responses["unknown"]
        return responses["timeline"]

    api = SenseExtendedApi(api_call, monitor_id="monitor-1", user_id="user-1")
    first = await api.refresh()
    failing = True
    second = await api.refresh()

    assert second == first


@pytest.mark.anyio
async def test_specific_appliance_details_are_normalized(responses) -> None:
    async def api_call(endpoint, payload):
        assert endpoint == "app/monitors/monitor-1/devices/microwave-1"
        assert payload == {}
        return {"device": responses["devices"][0]}

    api = SenseExtendedApi(api_call, monitor_id="monitor-1", user_id="user-1")
    details = await api.get_appliance_details("microwave-1")

    assert details is not None
    assert details.device_id == "microwave-1"
    assert details.device_type == "Microwave"
