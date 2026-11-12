from __future__ import annotations

import asyncio

import pytest

from aqara_device_samples import AQARA_DEVICE_SAMPLES
from piphi_runtime_testkit_python import assert_entities_response

from piphi_network_aqara.cloud.models import AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for background work to complete.")


@pytest.mark.asyncio
async def test_config_with_testkit_builders_delivers_telemetry_and_events(
    async_client,
    fake_cloud_client,
    mock_core_runtime,
    runtime_headers,
    config_payload,
) -> None:
    fake_cloud_client.devices = {
        "lumi.env.1001": AqaraCloudDevice(
            did="lumi.env.1001",
            name="Kitchen Climate",
            model="lumi.sensor_ht.agl02",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "lumi.sensor_ht.agl02": [
            AqaraResourceInfo(resource_id="0.1.85", name="Temperature value", description="Temperature value", access=3),
            AqaraResourceInfo(resource_id="0.2.85", name="Humidity value", description="Humidity value", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.env.1001": [
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="0.1.85", value="23.1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="0.2.85", value="48", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="8.0.2008", value="91", timestamp_ms=1710000000000),
        ]
    }

    payload = config_payload(
        config_id="cfg-runtime-1",
        device_id="lumi.env.1001",
        container_id="aqara-runtime-1",
        integration_id="aqara-open-api",
        extra={
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": "lumi.env.1001",
        },
    )
    headers = runtime_headers(container_id="aqara-runtime-1", internal_token="runtime-secret")

    response = await async_client.post("/config", json=payload, headers=headers)
    assert response.status_code == 200

    await wait_for(lambda: len(mock_core_runtime.telemetry_requests) >= 1)
    await wait_for(lambda: len(mock_core_runtime.event_requests) >= 1)

    telemetry_request = mock_core_runtime.assert_telemetry_sent(device_id="lumi.env.1001")
    event_request = mock_core_runtime.assert_event_sent(
        device_id="lumi.env.1001",
        config_id="cfg-runtime-1",
        event_type="device.configured",
    )
    telemetry_headers = {key.lower(): value for key, value in telemetry_request.headers.items()}
    event_headers = {key.lower(): value for key, value in event_request.headers.items()}

    assert telemetry_headers["x-container-id"] == "aqara-runtime-1"
    assert telemetry_headers["x-piphi-integration-token"] == "runtime-secret"
    assert event_headers["x-container-id"] == "aqara-runtime-1"
    assert event_headers["x-piphi-integration-token"] == "runtime-secret"
    assert telemetry_request.json_body["metrics"]["temperature_c"] == 23.1
    assert telemetry_request.json_body["metrics"]["humidity_percent"] == 48
    assert telemetry_request.json_body["metrics"]["battery_percent"] == 91
    assert (event_request.json_body.get("type") or event_request.json_body.get("event_type")) == "device.configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    tuple(sample for sample in AQARA_DEVICE_SAMPLES if sample.slug in {"smart_plug", "energy_plug", "dimmable_light", "camera_hub", "doorbell_camera", "curtain_motor", "door_lock", "door_lock_advanced"}),
    ids=lambda sample: sample.slug,
)
async def test_runtime_delivery_works_for_multiple_supported_device_families(
    async_client,
    fake_cloud_client,
    mock_core_runtime,
    runtime_headers,
    config_payload,
    sample,
) -> None:
    fake_cloud_client.devices = {sample.device.did: sample.device}
    fake_cloud_client.resources_by_model = {sample.device.model: list(sample.resources)}
    fake_cloud_client.values_by_did = {sample.device.did: list(sample.values)}

    payload = config_payload(
        config_id=f"cfg-{sample.slug}",
        device_id=sample.device.did,
        container_id=f"runtime-{sample.slug}",
        integration_id="aqara-open-api",
        extra={
            "region": "us",
            "app_id": "app-id-1",
            "key_id": "key-id-1",
            "app_key": "app-key-1",
            "access_token": "access-token-1",
            "open_id": "open-id-1",
            "did": sample.device.did,
        },
    )
    headers = runtime_headers(container_id=f"runtime-{sample.slug}", internal_token="runtime-secret")

    response = await async_client.post("/config", json=payload, headers=headers)
    assert response.status_code == 200

    await wait_for(lambda: len(mock_core_runtime.telemetry_requests) >= 1)
    await wait_for(lambda: len(mock_core_runtime.event_requests) >= 1)

    telemetry_request = mock_core_runtime.assert_telemetry_sent(device_id=sample.device.did)
    event_request = mock_core_runtime.assert_event_sent(
        device_id=sample.device.did,
        config_id=f"cfg-{sample.slug}",
        event_type="device.configured",
    )

    for key, expected_value in sample.expected_state.items():
        assert telemetry_request.json_body["metrics"][key] == expected_value
    assert (event_request.json_body.get("type") or event_request.json_body.get("event_type")) == "device.configured"


@pytest.mark.asyncio
async def test_entities_endpoint_matches_testkit_contract(
    async_client,
    fake_cloud_client,
    config_snapshot,
) -> None:
    fake_cloud_client.devices = {
        "lumi.motion.1002": AqaraCloudDevice(
            did="lumi.motion.1002",
            name="Hall Motion",
            model="aqara.motion.fp1e",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "aqara.motion.fp1e": [
            AqaraResourceInfo(resource_id="2.1.85", name="presence", description="presence", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "lumi.motion.1002": [
            AqaraResourceValue(subject_id="lumi.motion.1002", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.motion.1002", resource_id="8.0.2008", value="76", timestamp_ms=1710000000000),
        ]
    }

    snapshot = config_snapshot(
        container_id="aqara-runtime-entities",
        integration_id="aqara-open-api",
        generation=3,
        configs=[
            {
                "id": "cfg-entities-1",
                "config_id": "cfg-entities-1",
                "device_id": "lumi.motion.1002",
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "lumi.motion.1002",
            }
        ],
        extra={"reason": "entity_contract_test"},
    )

    response = await async_client.post("/configs/sync", json=snapshot)
    assert response.status_code == 200

    entities_response = await async_client.get("/entities")
    assert entities_response.status_code == 200
    payload = assert_entities_response(entities_response.json())

    entity = next(item for item in payload["entities"] if item["config_id"] == "cfg-entities-1")
    assert entity["device_id"] == "lumi.motion.1002"
    assert "presence_detected" in entity["capabilities"]
    assert entity["dashboard"]["default_widget"] == "presence-card"


@pytest.mark.asyncio
async def test_refresh_emits_camera_transition_events(
    async_client,
    fake_cloud_client,
    config_payload,
) -> None:
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
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.2.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.3.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="0", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id="cfg-camera-events-1",
            device_id="aqara.camera.1013",
            container_id="aqara-camera-events",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "aqara.camera.1013",
            },
        ),
    )
    assert response.status_code == 200

    fake_cloud_client.values_by_did["aqara.camera.1013"] = [
        AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="1", timestamp_ms=1710000001000),
        AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.2.85", value="1", timestamp_ms=1710000001000),
        AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.3.85", value="1", timestamp_ms=1710000001000),
        AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="0", timestamp_ms=1710000001000),
        AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="1", timestamp_ms=1710000001000),
    ]

    refresh_response = await async_client.post(
        "/command",
        json={"command": "refresh", "entity_id": "device:cfg-camera-events-1"},
    )
    assert refresh_response.status_code == 200

    events_response = await async_client.get("/events")
    assert events_response.status_code == 200
    payload = events_response.json()
    event_types = {
        event.get("type") or event.get("event_type")
        for event in payload.get("events", [])
        if isinstance(event, dict)
    }

    assert "aqara.camera.motion.detected" in event_types
    assert "aqara.camera.person.detected" in event_types
    assert "aqara.camera.audio.detected" in event_types
    assert "aqara.camera.privacy_mode.disabled" in event_types
    assert "aqara.camera.recording.enabled" in event_types


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "capability",
        "model",
        "resource_id",
        "resource_name",
        "detected_event",
        "cleared_event",
        "severity",
    ),
    (
        (
            "smoke_alarm",
            "aqara.smoke.acn03",
            "3.3.85",
            "Smoke alarm",
            "aqara.safety.smoke.detected",
            "aqara.safety.smoke.cleared",
            "critical",
        ),
        (
            "leak_detected",
            "aqara.water.wleak01",
            "3.2.85",
            "Water leak",
            "aqara.safety.leak.detected",
            "aqara.safety.leak.cleared",
            "warning",
        ),
        (
            "tamper_detected",
            "aqara.lock.d200",
            "6.2.85",
            "Forced entry tamper alarm",
            "aqara.access.forced_open",
            "aqara.access.forced_open.cleared",
            "warning",
        ),
        (
            "lock_jammed",
            "aqara.lock.d200",
            "6.3.85",
            "Lock jam alarm",
            "aqara.access.lock_jammed",
            "aqara.access.lock_jam.cleared",
            "warning",
        ),
        (
            "gas_alarm",
            "aqara.gas.acn02",
            "3.4.85",
            "Natural gas alarm",
            "aqara.safety.gas.detected",
            "aqara.safety.gas.cleared",
            "critical",
        ),
    ),
)
async def test_refresh_emits_security_transitions_without_initial_false_alarm(
    async_client,
    fake_cloud_client,
    config_payload,
    capability,
    model,
    resource_id,
    resource_name,
    detected_event,
    cleared_event,
    severity,
) -> None:
    device_id = f"test.{capability}"
    config_id = f"cfg-{capability}"
    fake_cloud_client.devices = {
        device_id: AqaraCloudDevice(
            did=device_id,
            name=resource_name,
            model=model,
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        model: [
            AqaraResourceInfo(
                resource_id=resource_id,
                name=resource_name,
                description=resource_name,
                access=3,
            )
        ]
    }
    fake_cloud_client.values_by_did = {
        device_id: [
            AqaraResourceValue(
                subject_id=device_id,
                resource_id=resource_id,
                value="0",
                timestamp_ms=1710000000000,
            )
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id=config_id,
            device_id=device_id,
            container_id=f"runtime-{capability}",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": device_id,
            },
        ),
    )
    assert response.status_code == 200

    initial_events = (await async_client.get("/events")).json()["events"]
    initial_types = {event.get("type") or event.get("event_type") for event in initial_events}
    assert detected_event not in initial_types
    assert cleared_event not in initial_types

    for value, expected_event in (("1", detected_event), ("0", cleared_event)):
        fake_cloud_client.values_by_did[device_id] = [
            AqaraResourceValue(
                subject_id=device_id,
                resource_id=resource_id,
                value=value,
                timestamp_ms=1710000001000 + int(value),
            )
        ]
        refresh_response = await async_client.post(
            "/command",
            json={"command": "refresh", "entity_id": f"device:{config_id}"},
        )
        assert refresh_response.status_code == 200

        events = (await async_client.get("/events")).json()["events"]
        event = next(
            item
            for item in events
            if (item.get("type") or item.get("event_type")) == expected_event
        )
        assert event["severity"] == severity
        assert event["payload"]["capability"] == capability
        assert event["payload"]["previous_value"] is (value == "0")
        assert event["payload"]["current_value"] is (value == "1")


@pytest.mark.asyncio
async def test_push_resource_report_updates_camera_state_and_events(
    async_client,
    fake_cloud_client,
    config_payload,
) -> None:
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
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.2.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.3.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="0", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id="cfg-camera-push-1",
            device_id="aqara.camera.1013",
            container_id="aqara-camera-push",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "aqara.camera.1013",
            },
        ),
    )
    assert response.status_code == 200

    push_response = await async_client.post(
        "/push/aqara",
        headers={"token": "access-token-1"},
        json={
            "msgId": "push-1",
            "openId": "open-id-1",
            "time": "1710000001000",
            "msgType": "resource_report",
            "data": [
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "2.1.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                    "triggerSource": {"type": 1, "time": "1710000001"},
                },
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "2.2.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "2.3.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "7.1.85",
                    "value": "0",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "7.2.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
            ],
        },
    )

    assert push_response.status_code == 200
    assert push_response.json()["handled"] == 5

    state_response = await async_client.get("/state")
    state_payload = state_response.json()
    camera_state = state_payload["state"]["cfg-camera-push-1"]["state"]
    assert camera_state["motion_detected"] is True
    assert camera_state["person_detected"] is True
    assert camera_state["audio_detected"] is True
    assert camera_state["privacy_mode"] is False
    assert camera_state["recording_enabled"] is True

    events_response = await async_client.get("/events")
    assert events_response.status_code == 200
    payload = events_response.json()
    event_types = {
        event.get("type") or event.get("event_type")
        for event in payload.get("events", [])
        if isinstance(event, dict)
    }
    assert "aqara.camera.motion.detected" in event_types
    assert "aqara.camera.person.detected" in event_types
    assert "aqara.camera.audio.detected" in event_types
    assert "aqara.camera.privacy_mode.disabled" in event_types
    assert "aqara.camera.recording.enabled" in event_types
    assert "aqara.resource_report" in event_types


@pytest.mark.asyncio
async def test_push_resource_report_updates_doorbell_state_and_events(
    async_client,
    fake_cloud_client,
    config_payload,
) -> None:
    fake_cloud_client.devices = {
        "aqara.doorbell.1015": AqaraCloudDevice(
            did="aqara.doorbell.1015",
            name="Front Doorbell",
            model="aqara.doorbell.g4",
            state=1,
        )
    }
    fake_cloud_client.resources_by_model = {
        "aqara.doorbell.g4": [
            AqaraResourceInfo(resource_id="2.4.85", name="Doorbell ring", description="doorbell ring event", access=3),
            AqaraResourceInfo(resource_id="2.5.85", name="Person detected", description="human detected", access=3),
            AqaraResourceInfo(resource_id="8.0.2010", name="Low battery alarm", description="low battery", access=3),
        ]
    }
    fake_cloud_client.values_by_did = {
        "aqara.doorbell.1015": [
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="2.4.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="2.5.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="8.0.2010", value="1", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id="cfg-doorbell-push-1",
            device_id="aqara.doorbell.1015",
            container_id="aqara-doorbell-push",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "aqara.doorbell.1015",
            },
        ),
    )
    assert response.status_code == 200

    push_response = await async_client.post(
        "/push/aqara",
        headers={"token": "access-token-1"},
        json={
            "msgId": "push-doorbell-1",
            "openId": "open-id-1",
            "time": "1710000001000",
            "msgType": "resource_report",
            "data": [
                {
                    "subjectId": "aqara.doorbell.1015",
                    "resourceId": "2.4.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
                {
                    "subjectId": "aqara.doorbell.1015",
                    "resourceId": "2.5.85",
                    "value": "1",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
                {
                    "subjectId": "aqara.doorbell.1015",
                    "resourceId": "8.0.2010",
                    "value": "0",
                    "time": "1710000001000",
                    "statusCode": 0,
                },
            ],
        },
    )

    assert push_response.status_code == 200
    assert push_response.json()["handled"] == 3

    state_response = await async_client.get("/state")
    state_payload = state_response.json()
    doorbell_state = state_payload["state"]["cfg-doorbell-push-1"]["state"]
    assert doorbell_state["doorbell_pressed"] is True
    assert doorbell_state["person_detected"] is True
    assert doorbell_state["battery_low"] is False

    events_response = await async_client.get("/events")
    assert events_response.status_code == 200
    payload = events_response.json()
    event_types = {
        event.get("type") or event.get("event_type")
        for event in payload.get("events", [])
        if isinstance(event, dict)
    }
    assert "aqara.doorbell.pressed" in event_types
    assert "aqara.camera.person.detected" in event_types
    assert "aqara.resource_report" in event_types


@pytest.mark.asyncio
async def test_duplicate_push_msg_id_is_ignored_and_reported_in_diagnostics(
    async_client,
    fake_cloud_client,
    config_payload,
) -> None:
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
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="0", timestamp_ms=1710000000000),
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id="cfg-camera-dedupe-1",
            device_id="aqara.camera.1013",
            container_id="aqara-camera-dedupe",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "aqara.camera.1013",
            },
        ),
    )
    assert response.status_code == 200

    push_payload = {
        "msgId": "push-dup-1",
        "openId": "open-id-1",
        "time": "1710000001000",
        "msgType": "resource_report",
        "data": [
            {
                "subjectId": "aqara.camera.1013",
                "resourceId": "2.1.85",
                "value": "1",
                "time": "1710000001000",
                "statusCode": 0,
            }
        ],
    }

    first_response = await async_client.post("/push/aqara", headers={"token": "access-token-1"}, json=push_payload)
    second_response = await async_client.post("/push/aqara", headers={"token": "access-token-1"}, json=push_payload)

    assert first_response.status_code == 200
    assert first_response.json()["duplicate"] is False
    assert second_response.status_code == 200
    assert second_response.json()["duplicate"] is True
    assert second_response.json()["handled"] == 0

    diagnostics_response = await async_client.get("/diagnostics")
    assert diagnostics_response.status_code == 200
    push_diagnostics = diagnostics_response.json()["diagnostics"]["push"]
    assert push_diagnostics["tracked_msg_id_count"] == 1
    assert push_diagnostics["status"]["received_count"] == 2
    assert push_diagnostics["status"]["duplicate_count"] == 1
    assert push_diagnostics["status"]["last_msg_id"] == "push-dup-1"


@pytest.mark.asyncio
async def test_stale_push_resource_report_is_ignored_and_counted_in_diagnostics(
    async_client,
    fake_cloud_client,
    config_payload,
) -> None:
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
        ]
    }
    fake_cloud_client.values_by_did = {
        "aqara.camera.1013": [
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="1", timestamp_ms=1710000002000),
        ]
    }

    response = await async_client.post(
        "/config",
        json=config_payload(
            config_id="cfg-camera-stale-1",
            device_id="aqara.camera.1013",
            container_id="aqara-camera-stale",
            integration_id="aqara-open-api",
            extra={
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": "aqara.camera.1013",
            },
        ),
    )
    assert response.status_code == 200

    push_response = await async_client.post(
        "/push/aqara",
        headers={"token": "access-token-1"},
        json={
            "msgId": "push-stale-1",
            "openId": "open-id-1",
            "time": "1710000001000",
            "msgType": "resource_report",
            "data": [
                {
                    "subjectId": "aqara.camera.1013",
                    "resourceId": "2.1.85",
                    "value": "0",
                    "time": "1710000001000",
                    "statusCode": 0,
                }
            ],
        },
    )

    assert push_response.status_code == 200
    assert push_response.json()["handled"] == 0

    state_response = await async_client.get("/state")
    state_payload = state_response.json()
    camera_state = state_payload["state"]["cfg-camera-stale-1"]["state"]
    assert camera_state["motion_detected"] is True
    assert camera_state["raw_resource_timestamps_ms"]["2.1.85"] == 1710000002000

    diagnostics_response = await async_client.get("/diagnostics")
    assert diagnostics_response.status_code == 200
    push_diagnostics = diagnostics_response.json()["diagnostics"]["push"]
    assert push_diagnostics["status"]["stale_count"] == 1
    assert push_diagnostics["status"]["last_msg_id"] == "push-stale-1"
    assert push_diagnostics["status"]["last_stale_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", AQARA_DEVICE_SAMPLES, ids=lambda sample: sample.slug)
async def test_entities_endpoint_matches_supported_device_family_catalog(
    async_client,
    fake_cloud_client,
    config_snapshot,
    sample,
) -> None:
    fake_cloud_client.devices = {sample.device.did: sample.device}
    fake_cloud_client.resources_by_model = {sample.device.model: list(sample.resources)}
    fake_cloud_client.values_by_did = {sample.device.did: list(sample.values)}

    snapshot = config_snapshot(
        container_id=f"runtime-{sample.slug}",
        integration_id="aqara-open-api",
        generation=4,
        configs=[
            {
                "id": f"cfg-{sample.slug}",
                "config_id": f"cfg-{sample.slug}",
                "device_id": sample.device.did,
                "region": "us",
                "app_id": "app-id-1",
                "key_id": "key-id-1",
                "app_key": "app-key-1",
                "access_token": "access-token-1",
                "open_id": "open-id-1",
                "did": sample.device.did,
            }
        ],
        extra={"reason": f"catalog_{sample.slug}"},
    )

    response = await async_client.post("/configs/sync", json=snapshot)
    assert response.status_code == 200

    entities_response = await async_client.get("/entities")
    assert entities_response.status_code == 200
    payload = assert_entities_response(entities_response.json())

    entity = next(item for item in payload["entities"] if item["config_id"] == f"cfg-{sample.slug}")
    assert entity["device_id"] == sample.device.did
    assert entity["dashboard"]["default_widget"] == sample.expected_default_widget
    for key in sample.expected_state:
        assert key in entity["capabilities"]
    command_ids = {command["id"] for command in entity["available_commands"]}
    for command_id in sample.expected_commands:
        assert command_id in command_ids
