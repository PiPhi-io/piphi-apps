from __future__ import annotations

import pytest
from pydantic import ValidationError

from piphi_network_knx.schemas import DeviceConfig


def _config(**updates):
    payload = {
        "id": "office",
        "host": "192.0.2.10",
        "allow_writes": True,
        "datapoints": [
            {
                "id": "light",
                "name": "Office light",
                "entity_type": "light",
                "dpt": "1.001",
                "state_address": "1/2/3",
                "command_address": "1/2/4",
                "writable": True,
            }
        ],
    }
    payload.update(updates)
    return payload


def test_valid_bounded_config() -> None:
    config = DeviceConfig.model_validate(_config())
    assert config.host == "192.0.2.10"
    assert config.datapoints[0].state_address == "1/2/3"


@pytest.mark.parametrize(
    "updates",
    [
        {"host": "gateway.local"},
        {"allow_writes": False},
        {
            "datapoints": [
                {
                    "id": "x",
                    "name": "x",
                    "entity_type": "sensor",
                    "dpt": "1.001",
                    "state_address": "1/1/1",
                }
            ]
        },
        {
            "datapoints": [
                {
                    "id": "x",
                    "name": "x",
                    "entity_type": "switch",
                    "dpt": "1.001",
                    "state_address": "32/0/0",
                }
            ]
        },
    ],
)
def test_invalid_or_unsafe_config_fails_closed(updates) -> None:
    with pytest.raises(ValidationError):
        DeviceConfig.model_validate(_config(**updates))
