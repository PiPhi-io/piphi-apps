from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from piphi_network_bermuda_presence.schemas import DeviceConfig
from piphi_network_bermuda_presence.state import make_entry


def valid_config() -> dict[str, object]:
    return {
        "id": "home-presence",
        "gateway_url": "https://gateway.local",
        "api_token": "super-secret",
        "consumer_id": "presence-home",
        "selected_device_handles": ["ble_00000000000000000000000000000001"],
        "receivers": [{"receiver_id": "proxy-1", "area_id": "kitchen", "area_name": "Kitchen"}],
    }


def test_config_rejects_partial_auth_duplicates_and_unsafe_transport() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        DeviceConfig.model_validate({"id": "x", "gateway_url": "https://gateway.local", "selected_device_handles": ["x"]})
    duplicate = valid_config() | {"selected_device_handles": ["same", "same"]}
    with pytest.raises(ValidationError, match="unique"):
        DeviceConfig.model_validate(duplicate)
    insecure = valid_config() | {"gateway_url": "http://gateway.local"}
    with pytest.raises(ValidationError, match="HTTPS"):
        DeviceConfig.model_validate(insecure)


def test_runtime_entry_never_contains_gateway_token() -> None:
    entry = make_entry(DeviceConfig.model_validate(valid_config()))
    serialized = json.dumps(entry, default=str)
    assert "super-secret" not in serialized
    assert "api_token" not in entry["config"]
