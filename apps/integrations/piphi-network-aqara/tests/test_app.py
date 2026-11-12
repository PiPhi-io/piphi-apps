from __future__ import annotations

import pytest

from piphi_network_aqara.cloud.models import AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue


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
    assert "cfg-camera-diag-1" in push_diagnostics["subscribed_config_ids"]
    assert push_diagnostics["tracked_msg_id_count"] == 0
    assert push_diagnostics["status"]["received_count"] == 0
    assert push_diagnostics["status"]["duplicate_count"] == 0
