from piphi_network_daikin_onecta.normalization import normalize_devices, opaque_id


def provider_payload(*, connected: object = True, settable: bool = True):
    return (
        {
            "id": "gateway-private-id",
            "name": "House",
            "deviceModel": "Altherma",
            "managementPoints": [
                {
                    "embeddedId": "climateControl",
                    "name": "Living room",
                    "isCloudConnectionUp": {"value": connected},
                    "onOffMode": {"value": "on"},
                    "operationMode": {"value": "heating"},
                    "roomTemperature": {"value": 20.5},
                    "temperatureControl": {
                        "value": {
                            "operationModes": {
                                "heating": {
                                    "setpoints": {
                                        "roomTemperature": {
                                            "value": 21.0,
                                            "minValue": 15.0,
                                            "maxValue": 30.0,
                                            "stepValue": 0.5,
                                            "settable": settable,
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            ],
        },
    )


def test_normalizes_climate_without_exposing_provider_identity() -> None:
    point = normalize_devices("oauth-user-private", provider_payload())[0]
    assert point.device_id == opaque_id(
        "oauth-user-private", "gateway-private-id", "climateControl"
    )
    assert "oauth-user-private" not in point.device_id
    assert "gateway-private-id" not in point.device_id
    assert point.indoor_temperature_c == 20.5
    assert point.target_temperature_c == 21.0
    assert point.target_temperature_min_c == 15.0
    assert point.target_temperature_max_c == 30.0
    assert point.target_temperature_step_c == 0.5
    assert point.target_settable is True
    assert point.target_path == "/operationModes/heating/setpoints/roomTemperature"


def test_string_false_connection_is_not_truthy() -> None:
    point = normalize_devices("subject", provider_payload(connected="false"))[0]
    assert point.connected is False


def test_skips_non_climate_management_points() -> None:
    payload = ({"id": "gateway", "managementPoints": [{"embeddedId": "consumption"}]},)
    assert normalize_devices("subject", payload) == []
