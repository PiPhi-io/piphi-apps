from __future__ import annotations

import pytest

from piphi_network_aqara import runtime as runtime_module
from piphi_network_aqara.cloud.client import AqaraCloudAuthError
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
