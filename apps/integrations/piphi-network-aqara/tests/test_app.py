from __future__ import annotations

import pytest

from piphi_network_aqara import runtime as runtime_module
from piphi_network_aqara.cloud.client import AqaraCloudAuthError
from piphi_network_aqara.cloud.models import (
    AqaraCloudDevice,
    AqaraResourceInfo,
    AqaraResourceValue,
    AqaraScene,
    AqaraTraitInfo,
    AqaraTraitValue,
)


@pytest.mark.asyncio
async def test_discover_returns_devices(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "lumi.1234": AqaraCloudDevice(
            did="lumi.1234",
            name="Hallway Sensor",
            model="lumi.sensor_ht.agl02",
            state=1,
        )
    }

    response = await async_client.post(
        "/discover",
        json={
            "inputs": {
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["devices"][0]["did"] == "lumi.1234"
    assert payload["devices"][0]["device_model"] == "lumi.sensor_ht.agl02"
    assert "app_key" not in payload["devices"][0]
    assert "access_token" not in payload["devices"][0]
    assert "refresh_token" not in payload["devices"][0]


@pytest.mark.asyncio
async def test_config_sync_builds_state_and_supports_turn_on(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "lumi.5678": AqaraCloudDevice(
            did="lumi.5678",
            name="Desk Plug",
            model="lumi.plug.maus01",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "lumi.plug.maus01": [
            AqaraResourceInfo(resource_id="4.1.85", name="plug status", description="plug status", access=5),
            AqaraResourceInfo(resource_id="8.0.2001", name="Load power", description="Load power", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.5678": [
            AqaraResourceValue(subject_id="lumi.5678", resource_id="4.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.5678", resource_id="8.0.2001", value="12.4", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/configs/sync",
        json={
            "container_id": "container-1",
            "integration_id": "aqara-open-api",
            "generation": 1,
            "reason": "test_sync",
            "configs": [
                {
                    "id": "cfg-1",
                    "region": "us",
                    "app_id": "app-id-1",
                    "key_id": "key-id-1",
                    "app_key": "app-key-1",
                    "access_token": "access-token-1",
                    "open_id": "open-id-1",
                    "did": "lumi.5678"
                }
            ]
        },
    )

    assert response.status_code == 200
    entities_response = await async_client.get("/entities")
    state_response = await async_client.get("/state")
    command_response = await async_client.post(
        "/command",
        json={"command": "turn_on", "entity_id": "device:cfg-1"},
    )

    entities_payload = entities_response.json()
    state_payload = state_response.json()

    assert any(entity["device_id"] == "lumi.5678" for entity in entities_payload["entities"])
    assert state_payload["state"]["cfg-1"]["state"]["switch_on"] is False
    assert command_response.status_code == 200
    assert fake_cloud_client.writes == [("lumi.5678", "4.1.85", "1")]


@pytest.mark.asyncio
async def test_command_replays_idempotency_key_without_repeating_device_effect(
    async_client,
    fake_cloud_client,
) -> None:
    fake_cloud_client.devices = {
        "lumi.idempotency": AqaraCloudDevice(
            did="lumi.idempotency",
            name="Idempotent Plug",
            model="lumi.plug.maus01",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "lumi.plug.maus01": [
            AqaraResourceInfo(
                resource_id="4.1.85",
                name="plug status",
                description="plug status",
                access=5,
            )
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.idempotency": [
            AqaraResourceValue(
                subject_id="lumi.idempotency",
                resource_id="4.1.85",
                value="0",
                timestamp_ms=1710000000000,
            )
        ]
    }
    config_response = await async_client.post(
        "/config",
        json={
            "id": "cfg-idempotency",
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "lumi.idempotency",
        },
    )
    assert config_response.status_code == 200

    headers = {"X-PiPhi-Idempotency-Key": "aqara-action-idempotency-1"}
    payload = {"command": "turn_on", "entity_id": "device:cfg-idempotency"}
    first = await async_client.post("/command", json=payload, headers=headers)
    replay = await async_client.post("/command", json=payload, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert fake_cloud_client.writes == [("lumi.idempotency", "4.1.85", "1")]


@pytest.mark.asyncio
async def test_config_sync_uses_model_registry_for_cover_position(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "lumi.cover.1111": AqaraCloudDevice(
            did="lumi.cover.1111",
            name="Living Room Curtain",
            model="lumi.curtain.acn002",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "lumi.curtain.acn002": [
            AqaraResourceInfo(resource_id="14.7.111", name="position", description="position", access=5),
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.cover.1111": [
            AqaraResourceValue(subject_id="lumi.cover.1111", resource_id="14.7.111", value="34", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json={
            "id": "cfg-cover-1",
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "lumi.cover.1111",
        },
    )

    assert response.status_code == 200

    state_response = await async_client.get("/state")
    entities_response = await async_client.get("/entities")
    command_response = await async_client.post(
        "/command",
        json={"command": "set_position", "entity_id": "device:cfg-cover-1", "args": {"position": 82}},
    )

    state_payload = state_response.json()
    entities_payload = entities_response.json()

    assert state_payload["state"]["cfg-cover-1"]["state"]["cover_position"] == 34
    assert any("set_position" in {command["id"] for command in entity["available_commands"]} for entity in entities_payload["entities"] if entity["config_id"] == "cfg-cover-1")
    assert command_response.status_code == 200
    assert fake_cloud_client.writes == [("lumi.cover.1111", "14.7.111", "82")]


@pytest.mark.asyncio
async def test_config_sync_supports_light_brightness_control(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "lumi.light.1011": AqaraCloudDevice(
            did="lumi.light.1011",
            name="Bedroom Lamp",
            model="aqara.light.bulb_e27",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "aqara.light.bulb_e27": [
            AqaraResourceInfo(resource_id="4.1.85", name="Light switch", description="light switch", access=5),
            AqaraResourceInfo(resource_id="5.1.85", name="Brightness value", description="brightness level", access=5),
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.light.1011": [
            AqaraResourceValue(subject_id="lumi.light.1011", resource_id="4.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.light.1011", resource_id="5.1.85", value="64", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json={
            "id": "cfg-light-1",
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "lumi.light.1011",
        },
    )

    assert response.status_code == 200

    entities_response = await async_client.get("/entities")
    command_response = await async_client.post(
        "/command",
        json={"command": "set_brightness", "entity_id": "device:cfg-light-1", "args": {"value": 82}},
    )

    entities_payload = entities_response.json()

    assert any(
        "set_brightness" in {command["id"] for command in entity["available_commands"]}
        for entity in entities_payload["entities"]
        if entity["config_id"] == "cfg-light-1"
    )
    assert command_response.status_code == 200
    assert fake_cloud_client.writes == [("lumi.light.1011", "5.1.85", "82")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "resource_id", "resource_name", "minimum", "maximum", "command", "args", "expected_value"),
    (
        ("aqara.light.rgbct", "5.2.85", "ColorTemperature", 153, 500, "set_color_temperature", {"value": 250}, "250"),
        ("aqara.light.rgbct", "5.3.85", "Hue", 0, 360, "set_hue", {"value": 210}, "210"),
        ("aqara.light.rgbct", "5.4.85", "Saturation", 0, 100, "set_saturation", {"value": 65}, "65"),
        ("aqara.thermostat.e1", "0.8.85", "SetTemperature", 5, 30, "set_temperature", {"temperature_c": 21.5}, "21.5"),
        ("aqara.airpurifier.p1", "4.2.85", "FanSpeed", 0, 100, "set_fan_speed", {"speed": 40}, "40"),
    ),
)
async def test_config_negotiates_documented_common_device_controls(
    async_client,
    fake_cloud_client,
    model,
    resource_id,
    resource_name,
    minimum,
    maximum,
    command,
    args,
    expected_value,
) -> None:
    did = f"device.{command}"
    config_id = f"cfg-{command}"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name=command, model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [
            AqaraResourceInfo(
                resource_id=resource_id,
                name=resource_name,
                access=5,
                min_value=minimum,
                max_value=maximum,
            )
        ]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id=resource_id, value=str(minimum))]
    }

    configured = await async_client.post(
        "/config",
        json={
            "id": config_id,
            "region": "us",
            "app_id": "app-id",
            "key_id": "key-id",
            "app_key": "app-key",
            "access_token": "access-token",
            "open_id": "open-id",
            "did": did,
        },
    )
    response = await async_client.post(
        "/command",
        json={"command": command, "entity_id": f"device:{config_id}", "args": args},
    )

    assert configured.status_code == 200
    assert response.status_code == 200
    assert fake_cloud_client.writes == [(did, resource_id, expected_value)]


@pytest.mark.asyncio
async def test_temperature_and_color_temperature_require_vendor_bounds(async_client, fake_cloud_client) -> None:
    did = "device.unbounded"
    model = "aqara.thermostat.unbounded"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Unbounded", model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [AqaraResourceInfo(resource_id="0.8.85", name="SetTemperature", access=5)]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id="0.8.85", value="20")]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": "cfg-unbounded",
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200

    response = await async_client.post(
        "/command",
        json={"command": "set_temperature", "entity_id": "device:cfg-unbounded", "args": {"temperature_c": 21}},
    )
    assert response.status_code == 400
    assert fake_cloud_client.writes == []


@pytest.mark.asyncio
async def test_trait_modes_are_advertised_validated_and_written(async_client, fake_cloud_client) -> None:
    did = "lumi.airrtc.modes"
    model = "lumi.airrtc.aeu001"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Office HVAC", model=model, state=1)}
    fake_cloud_client.traits_by_model = {
        model: [
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="HeaterCoolerMode",
                readable=True,
                writable=True,
                supported_values={"Off": "0", "Heat": "1", "Cool": "2", "Auto": "3"},
            ),
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="FanMode",
                readable=True,
                writable=True,
                supported_values={"Auto": "0", "Low": "1", "High": "2"},
            ),
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="RockSetting",
                readable=True,
                writable=True,
                supported_values={"Off": "0", "Vertical": "1"},
            ),
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="AirflowDirection",
                readable=True,
                writable=True,
                supported_values={"Horizontal": "0", "Vertical": "1"},
            ),
        ]
    }
    fake_cloud_client.trait_values_by_did = {
        did: [
            AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="HeaterCoolerMode", value="1"),
            AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="FanMode", value="0"),
            AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="RockSetting", value="0"),
            AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="AirflowDirection", value="0"),
        ]
    }
    configured = await async_client.post(
        "/config",
        json={
            "id": "cfg-modes",
            "region": "us",
            "app_id": "app-id",
            "key_id": "key-id",
            "app_key": "app-key",
            "access_token": "access-token",
            "open_id": "open-id",
            "did": did,
        },
    )
    assert configured.status_code == 200
    entity = next(item for item in (await async_client.get("/entities")).json()["entities"] if item["config_id"] == "cfg-modes")
    assert {"set_hvac_mode", "set_fan_mode", "set_swing_mode", "set_airflow_direction"} <= {
        item["id"] for item in entity["available_commands"]
    }

    requests = (
        ("set_hvac_mode", {"mode": "cool"}),
        ("set_fan_mode", {"mode": "high"}),
        ("set_swing_mode", {"mode": "vertical"}),
        ("set_airflow_direction", {"direction": "vertical"}),
    )
    for command, args in requests:
        response = await async_client.post(
            "/command",
            json={"command": command, "entity_id": "device:cfg-modes", "args": args},
        )
        assert response.status_code == 200

    assert fake_cloud_client.trait_writes == [
        (did, 1, "Thermostat", "HeaterCoolerMode", "2"),
        (did, 1, "Thermostat", "FanMode", "2"),
        (did, 1, "Thermostat", "RockSetting", "1"),
        (did, 1, "Thermostat", "AirflowDirection", "1"),
    ]

    rejected = await async_client.post(
        "/command",
        json={"command": "set_hvac_mode", "entity_id": "device:cfg-modes", "args": {"mode": "dry"}},
    )
    assert rejected.status_code == 400
    assert "auto, cool, heat, off" in rejected.text
    assert len(fake_cloud_client.trait_writes) == 4


@pytest.mark.asyncio
async def test_cover_stop_uses_only_explicit_vendor_enum(async_client, fake_cloud_client) -> None:
    did = "lumi.cover.stop"
    model = "lumi.curtain.stop"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Curtain", model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [
            AqaraResourceInfo(
                resource_id="14.3.85",
                name="Curtain motor control",
                access=4,
                enums="0:open,1:close,2:stop",
            )
        ]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": "cfg-cover-stop",
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200
    response = await async_client.post(
        "/command",
        json={"command": "stop_cover", "entity_id": "device:cfg-cover-stop"},
    )
    assert response.status_code == 200
    assert fake_cloud_client.writes == [(did, "14.3.85", "2")]


@pytest.mark.asyncio
async def test_trait_push_updates_modes_and_emits_negotiated_remote_events(async_client, fake_cloud_client) -> None:
    did = "lumi.remote.traits"
    model = "lumi.remote.test"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Remote", model=model, state=1)}
    fake_cloud_client.traits_by_model = {
        model: [
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="HeaterCoolerMode",
                readable=True,
                writable=True,
                subscribable=True,
                supported_values={"Off": "0", "Heat": "1", "Cool": "2"},
            ),
            AqaraTraitInfo(
                endpoint_id=2,
                function_code="Button",
                trait_code="ButtonEvent",
                subscribable=True,
                supported_values={"Single Press": "0", "Double Press": "1"},
            ),
            AqaraTraitInfo(
                endpoint_id=3,
                function_code="Knob",
                trait_code="RotationEvent",
                subscribable=True,
                supported_values={"Rotate": "0", "Hold To Rotate": "1"},
            ),
            AqaraTraitInfo(
                endpoint_id=4,
                function_code="Cube",
                trait_code="CubeEvent",
                subscribable=True,
                supported_values={"Flip 90": "0", "Shake": "4"},
            ),
            AqaraTraitInfo(
                endpoint_id=5,
                function_code="Vibration",
                trait_code="VibrationEvent",
                subscribable=True,
                supported_values={"Move": "1", "Vibrate": "2"},
            ),
        ]
    }
    fake_cloud_client.trait_values_by_did = {
        did: [AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="HeaterCoolerMode", value="1")]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": "cfg-trait-push",
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200
    assert fake_cloud_client.trait_subscriptions == [
        [
            {
                "deviceId": did,
                "codePaths": [
                    "1.Thermostat.HeaterCoolerMode",
                    "2.Button.ButtonEvent",
                    "3.Knob.RotationEvent",
                    "4.Cube.CubeEvent",
                    "5.Vibration.VibrationEvent",
                ],
                "attach": "cfg-trait-push",
            }
        ]
    ]

    response = await async_client.post(
        "/push/aqara",
        headers={"token": "access-token"},
        json={
            "msgId": "trait-push-1",
            "msgType": "spec_report",
            "openId": "open-id",
            "time": "1762480477000",
            "data": [
                {
                    "endpointId": "1",
                    "functionCode": "Thermostat",
                    "traitCode": "HeaterCoolerMode",
                    "statusCode": 0,
                    "deviceId": did,
                    "time": "1762480477100",
                    "value": "2",
                },
                {
                    "endpointId": "2",
                    "functionCode": "Button",
                    "traitCode": "ButtonEvent",
                    "statusCode": 0,
                    "deviceId": did,
                    "time": "1762480477200",
                    "value": "1",
                    "triggerSource": {"type": 10, "time": "1762480477"},
                },
                {"endpointId": 3, "functionCode": "Knob", "traitCode": "RotationEvent", "statusCode": 0, "deviceId": did, "time": "1762480477300", "value": "1"},
                {"endpointId": 4, "functionCode": "Cube", "traitCode": "CubeEvent", "statusCode": 0, "deviceId": did, "time": "1762480477400", "value": "4"},
                {"endpointId": 5, "functionCode": "Vibration", "traitCode": "VibrationEvent", "statusCode": 0, "deviceId": did, "time": "1762480477500", "value": "2"},
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["handled"] == 5
    state = (await async_client.get("/state")).json()["state"]["cfg-trait-push"]["state"]
    assert state["hvac_mode"] == "cool"
    events = (await async_client.get("/events")).json()["events"]
    button_event = next(event for event in events if (event.get("type") or event.get("event_type")) == "aqara.button.event")
    assert button_event["payload"]["action"] == "double_press"
    assert button_event["payload"]["endpoint_id"] == 2
    assert "value" not in button_event["payload"]
    event_actions = {
        event.get("type") or event.get("event_type"): event["payload"]["action"]
        for event in events
        if (event.get("type") or event.get("event_type")) in {
            "aqara.rotation.event",
            "aqara.cube.event",
            "aqara.vibration.event",
        }
    }
    assert event_actions == {
        "aqara.rotation.event": "hold_to_rotate",
        "aqara.cube.event": "shake",
        "aqara.vibration.event": "vibrate",
    }

    unknown = await async_client.post(
        "/push/aqara",
        headers={"token": "access-token"},
        json={
            "msgId": "trait-push-unknown",
            "msgType": "spec_report",
            "openId": "open-id",
            "data": [{"endpointId": 2, "functionCode": "Button", "traitCode": "ButtonEvent", "statusCode": 0, "deviceId": did, "value": "99"}],
        },
    )
    assert unknown.status_code == 200
    assert unknown.json()["handled"] == 0

    assert (await async_client.post("/deconfigure", json={"config": {"config_id": "cfg-trait-push"}})).status_code == 200
    assert fake_cloud_client.trait_unsubscriptions == [
        [
            {
                "deviceId": did,
                "codePaths": [
                    "1.Thermostat.HeaterCoolerMode",
                    "2.Button.ButtonEvent",
                    "3.Knob.RotationEvent",
                    "4.Cube.CubeEvent",
                    "5.Vibration.VibrationEvent",
                ],
            }
        ]
    ]


@pytest.mark.asyncio
async def test_scene_execution_accepts_only_discovered_selectors(async_client, fake_cloud_client) -> None:
    did = "lumi.scene.device"
    model = "lumi.switch.scene"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Scene Switch", model=model, state=1)}
    fake_cloud_client.scenes_by_did = {
        did: [AqaraScene(scene_id="AL.829804945617997824", name="Movie Time", model="app.scene.v1", localize=0)]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": "cfg-scenes",
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200
    entity = next(item for item in (await async_client.get("/entities")).json()["entities"] if item["config_id"] == "cfg-scenes")
    command = next(item for item in entity["available_commands"] if item["id"] == "run_scene")
    selector = command["options"][0]["value"]
    assert selector.startswith("scene_")
    assert "AL.829804945617997824" not in str(command)

    rejected = await async_client.post(
        "/command",
        json={"command": "run_scene", "entity_id": "device:cfg-scenes", "args": {"scene_id": "AL.829804945617997824"}},
    )
    assert rejected.status_code == 400
    assert fake_cloud_client.scene_runs == []
    unknown = await async_client.post(
        "/command",
        json={"command": "run_scene", "entity_id": "device:cfg-scenes", "args": {"scene": "scene_not_discovered"}},
    )
    assert unknown.status_code == 400

    executed = await async_client.post(
        "/command",
        json={"command": "run_scene", "entity_id": "device:cfg-scenes", "args": {"scene": selector}},
    )
    assert executed.status_code == 200
    assert executed.json()["scene"] == selector
    assert fake_cloud_client.scene_runs == ["AL.829804945617997824"]


@pytest.mark.asyncio
async def test_config_subscribes_bound_resources_for_push_updates(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "aqara.camera.1013": AqaraCloudDevice(
            did="aqara.camera.1013",
            name="Nursery Camera",
            model="aqara.camera.g3",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "aqara.camera.g3": [
            AqaraResourceInfo(resource_id="2.1.85", name="Camera motion", description="camera motion detected", access=3),
            AqaraResourceInfo(resource_id="2.2.85", name="Person detected", description="person detected", access=3),
            AqaraResourceInfo(resource_id="2.3.85", name="Audio detected", description="audio detected", access=3),
            AqaraResourceInfo(resource_id="7.1.85", name="Privacy mode", description="camera privacy mode", access=3),
            AqaraResourceInfo(resource_id="7.2.85", name="Recording", description="sd recording switch", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "aqara.camera.1013": [
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.2.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.3.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="1", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json={
            "id": "cfg-camera-sub-1",
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "aqara.camera.1013",
        },
    )

    assert response.status_code == 200
    assert fake_cloud_client.subscriptions == [[{
        "subjectId": "aqara.camera.1013",
        "resourceIds": ["2.1.85", "2.2.85", "2.3.85", "7.1.85", "7.2.85"],
        "attach": "cfg-camera-sub-1",
    }]]


@pytest.mark.asyncio
async def test_ui_config_and_diagnostics_expose_push_webhook_details(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "aqara.camera.1013": AqaraCloudDevice(
            did="aqara.camera.1013",
            name="Nursery Camera",
            model="aqara.camera.g3",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "aqara.camera.g3": [
            AqaraResourceInfo(resource_id="2.1.85", name="Camera motion", description="camera motion detected", access=3),
            AqaraResourceInfo(resource_id="7.1.85", name="Privacy mode", description="camera privacy mode", access=3),
            AqaraResourceInfo(resource_id="7.2.85", name="Recording", description="sd recording switch", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "aqara.camera.1013": [
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="1", timestamp_ms=1710000000000),
        ]
    }

    config_response = await async_client.post(
        "/config",
        json={
            "id": "cfg-camera-diag-1",
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "aqara.camera.1013",
        },
    )
    assert config_response.status_code == 200

    ui_response = await async_client.get("/ui-config")
    diagnostics_response = await async_client.get("/diagnostics")

    assert ui_response.status_code == 200
    assert diagnostics_response.status_code == 200

    ui_payload = ui_response.json()
    diagnostics_payload = diagnostics_response.json()

    assert ui_payload["push"]["channel"] == "http"
    assert ui_payload["push"]["webhook_path"] == "/push/aqara"
    assert ui_payload["push"]["webhook_url"].endswith("/push/aqara")
    assert ui_payload["push"]["header_name"] == "token"

    push_diagnostics = diagnostics_payload["diagnostics"]["push"]
    assert push_diagnostics["webhook_path"] == "/push/aqara"
    assert push_diagnostics["webhook_url"].endswith("/push/aqara")
    assert push_diagnostics["header_name"] == "token"
    assert push_diagnostics["active_subscription_count"] == 1
    assert push_diagnostics["tracked_msg_id_count"] == 0
    assert push_diagnostics["status"]["received_count"] == 0
    assert push_diagnostics["status"]["duplicate_count"] == 0


@pytest.mark.asyncio
async def test_config_rejects_attacker_api_domain(async_client) -> None:
    response = await async_client.post(
        "/config",
        json={
            "id": "cfg-attacker-domain",
            "region": "us",
            "app_id": "app-id",
            "key_id": "key-id",
            "app_key": "app-key",
            "access_token": "access-token",
            "open_id": "open-id",
            "did": "lumi.redirect",
            "custom_api_domain": "https://attacker.example",
        },
    )
    assert response.status_code == 400
    assert "official endpoint" in response.text


@pytest.mark.asyncio
async def test_diagnostics_expose_counts_without_config_or_task_ids(async_client, fake_cloud_client) -> None:
    config_id = "cfg-private-diagnostics-canary"
    did = "lumi.private-diagnostics-canary"
    model = "lumi.plug.maus01"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Private diagnostics", model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [AqaraResourceInfo(resource_id="4.1.85", name="plug status", access=5)]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id="4.1.85", value="0")]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": config_id,
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200
    diagnostics = (await async_client.get("/diagnostics")).json()["diagnostics"]
    serialized = str(diagnostics)
    assert diagnostics["active_config_count"] == 1
    assert diagnostics["poll_task_count"] == 1
    assert diagnostics["poll_summary"]["tracked_config_count"] == 1
    assert diagnostics["state_summary"]["snapshot_count"] == 1
    assert config_id not in serialized
    assert did not in serialized
    assert "active_config_ids" not in diagnostics
    assert "poll_task_ids" not in diagnostics
    assert "subscribed_config_ids" not in diagnostics["push"]


@pytest.mark.asyncio
async def test_runtime_logs_use_hashed_reference_and_omit_ids_and_pii(async_client, fake_cloud_client, caplog) -> None:
    config_id = "cfg-log-canary-private"
    did = "lumi.log-canary-private"
    open_id = "open-log-canary-private"
    account = "private-log@example.test"
    device_name = "Private Bedroom Canary"
    model = "lumi.plug.maus01"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name=device_name, model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [AqaraResourceInfo(resource_id="4.1.85", name="plug status", access=5)]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id="4.1.85", value="0")]
    }
    caplog.set_level("INFO", logger="piphi_network_aqara.runtime")
    response = await async_client.post(
        "/config",
        json={
            "id": config_id,
            "region": "us",
            "app_id": "app-id",
            "key_id": "key-id",
            "app_key": "app-key",
            "access_token": "access-token",
            "open_id": open_id,
            "account": account,
            "did": did,
            "device_name": device_name,
        },
    )
    assert response.status_code == 200
    log_text = caplog.text
    assert "ref=" in log_text
    for private_value in (config_id, did, open_id, account, device_name):
        assert private_value not in log_text


@pytest.mark.asyncio
async def test_diagnostics_and_state_recursively_redact_canary_secrets_and_pii(async_client, fake_cloud_client) -> None:
    canary = "AQARA-CANARY-SECRET-7d28c2"
    fake_cloud_client.devices = {
        "lumi.canary": AqaraCloudDevice(did="lumi.canary", name="Private room", model="lumi.plug.maus01", state=1)
    }
    fake_cloud_client.resources_by_model = {
        "lumi.plug.maus01": [AqaraResourceInfo(resource_id="4.1.85", name="plug status", access=5)]
    }
    fake_cloud_client.values_by_did = {
        "lumi.canary": [AqaraResourceValue(subject_id="lumi.canary", resource_id="4.1.85", value=canary)]
    }
    response = await async_client.post(
        "/config",
        json={
            "id": "cfg-canary",
            "region": "us",
            "app_id": "app-id",
            "key_id": "key-id",
            "app_key": canary,
            "access_token": f"access-{canary}",
            "refresh_token": f"refresh-{canary}",
            "open_id": "private-open-id",
            "account": "person@example.test",
            "did": "lumi.canary",
        },
    )
    assert response.status_code == 200

    state_text = (await async_client.get("/state")).text
    diagnostics_text = (await async_client.get("/diagnostics")).text
    events_text = (await async_client.get("/events")).text
    command_text = (
        await async_client.post("/command", json={"command": "refresh", "entity_id": "device:cfg-canary"})
    ).text

    assert canary not in state_text
    assert canary not in diagnostics_text
    assert canary not in events_text
    assert canary not in command_text
    assert canary not in str(runtime_module.registry.state_snapshots)
    assert "person@example.test" not in diagnostics_text
    assert "Private room" not in diagnostics_text
    assert "private-open-id" not in diagnostics_text


@pytest.mark.asyncio
async def test_invalid_refresh_token_sets_actionable_reauth_and_replacement_recovers(
    async_client,
    fake_cloud_client,
    monkeypatch,
) -> None:
    did = "lumi.reauth"
    model = "lumi.plug.maus01"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Reauth plug", model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [AqaraResourceInfo(resource_id="4.1.85", name="plug status", access=5)]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id="4.1.85", value="0")]
    }
    config = {
        "id": "cfg-reauth",
        "region": "us",
        "app_id": "app-id",
        "key_id": "key-id",
        "app_key": "app-key",
        "access_token": "expired-access",
        "refresh_token": "rotated-away-refresh",
        "open_id": "open-id",
        "did": did,
    }
    assert (await async_client.post("/config", json=config)).status_code == 200
    original_resource_values = fake_cloud_client.resource_values

    async def rejected_read(*_args, **_kwargs):
        raise AqaraCloudAuthError("credential rejected rotated-away-refresh")

    async def rejected_refresh(*_args, **_kwargs):
        raise AqaraCloudAuthError("invalid_grant rotated-away-refresh")

    monkeypatch.setattr(fake_cloud_client, "resource_values", rejected_read)
    monkeypatch.setattr(fake_cloud_client, "refresh_access_token", rejected_refresh)
    refresh = await async_client.post("/command", json={"command": "refresh", "entity_id": "device:cfg-reauth"})
    assert refresh.status_code == 401
    assert "rotated-away-refresh" not in refresh.text

    state = (await async_client.get("/state")).json()["state"]["cfg-reauth"]["state"]
    assert state["auth_state"] == "reauth_required"
    assert state["reauth_reason"] == "refresh_token_rejected"
    assert "reauthenticate" in refresh.text.lower()

    monkeypatch.setattr(fake_cloud_client, "resource_values", original_resource_values)
    replacement = {**config, "access_token": "replacement-access", "refresh_token": "replacement-refresh"}
    assert (await async_client.post("/config", json=replacement)).status_code == 200
    assert runtime_module.registry.get("cfg-reauth")["auth_state"] == "authenticated"


@pytest.mark.asyncio
async def test_region_and_identity_changes_fail_closed_without_removing_existing_config(async_client, fake_cloud_client) -> None:
    fake_cloud_client.devices = {
        "lumi.identity": AqaraCloudDevice(did="lumi.identity", name="Identity plug", model="lumi.plug.maus01", state=1)
    }
    fake_cloud_client.resources_by_model = {
        "lumi.plug.maus01": [AqaraResourceInfo(resource_id="4.1.85", name="plug status", access=5)]
    }
    fake_cloud_client.values_by_did = {
        "lumi.identity": [AqaraResourceValue(subject_id="lumi.identity", resource_id="4.1.85", value="0")]
    }
    config = {
        "id": "cfg-identity",
        "region": "us",
        "app_id": "app-id",
        "key_id": "key-id",
        "app_key": "app-key",
        "access_token": "access-token",
        "open_id": "open-id",
        "did": "lumi.identity",
    }
    assert (await async_client.post("/config", json=config)).status_code == 200
    assert (await async_client.post("/config", json={**config, "region": "eu"})).status_code == 409
    assert runtime_module.registry.get("cfg-identity")["region"] == "us"

    unsupported = await async_client.post("/discover", json={"inputs": {**config, "region": "moon"}})
    assert unsupported.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_value", [-1, 101, 1.5, True, "nan", "inf"])
async def test_dynamic_commands_reject_unsafe_values(async_client, fake_cloud_client, unsafe_value) -> None:
    did = "lumi.bounded"
    model = "aqara.light.bulb_e27"
    fake_cloud_client.devices = {did: AqaraCloudDevice(did=did, name="Bounded light", model=model, state=1)}
    fake_cloud_client.resources_by_model = {
        model: [AqaraResourceInfo(resource_id="5.1.85", name="Brightness", access=5, min_value=0, max_value=100)]
    }
    fake_cloud_client.values_by_did = {
        did: [AqaraResourceValue(subject_id=did, resource_id="5.1.85", value="50")]
    }
    assert (
        await async_client.post(
            "/config",
            json={
                "id": "cfg-bounded",
                "region": "us",
                "app_id": "app-id",
                "key_id": "key-id",
                "app_key": "app-key",
                "access_token": "access-token",
                "open_id": "open-id",
                "did": did,
            },
        )
    ).status_code == 200
    response = await async_client.post(
        "/command",
        json={"command": "set_brightness", "entity_id": "device:cfg-bounded", "args": {"value": unsafe_value}},
    )
    assert response.status_code == 400
    assert fake_cloud_client.writes == []
