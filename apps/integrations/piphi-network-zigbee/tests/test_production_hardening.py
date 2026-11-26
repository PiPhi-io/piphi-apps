from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_zigbee import state as runtime_state
from piphi_network_zigbee.app import create_app
from piphi_network_zigbee.persistence import load_entries, save_entries
from piphi_network_zigbee.security import REDACTED, redact
from piphi_network_zigbee.sidecar_client import Zigbee2MqttSidecarClient
from piphi_network_zigbee.zigbee_devices import (
    available_commands_for,
    entities_from_entry,
    normalize_zigbee2mqtt_device,
)


@pytest.mark.anyio
async def test_production_auth_fails_closed_with_only_health_public(monkeypatch) -> None:
    runtime_state.stop_mqtt_subscriptions()
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 503
        monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
        assert (await client.get("/entities")).status_code == 401
        assert (
            await client.get(
                "/entities", headers={"x-piphi-integration-token": "runtime-secret"}
            )
        ).status_code == 200


def test_recursive_redaction_covers_keys_network_identity_and_inline_values() -> None:
    value = {
        "nested": [{"network_key": [1, 2]}, {"ieee_address": "0x00124b"}],
        "message": "password=canary-secret",
    }
    result = redact(value)
    assert result["nested"][0]["network_key"] == REDACTED
    assert result["nested"][1]["ieee_address"] == REDACTED
    assert "canary-secret" not in json.dumps(result)


def test_endpoint_identity_and_composite_exposes_are_preserved_without_overadvertising() -> None:
    device = normalize_zigbee2mqtt_device(
        {
            "friendly_name": "dual_switch",
            "ieee_address": "0x00124b0000000001",
            "definition": {
                "exposes": [
                    {
                        "type": "composite",
                        "endpoint": "left",
                        "features": [
                            {"property": "state", "type": "binary", "access": 7},
                            {"property": "lock", "type": "binary", "access": 7},
                        ],
                    },
                    {
                        "type": "composite",
                        "endpoint": "right",
                        "features": [{"property": "state", "type": "binary", "access": 7}],
                    },
                ]
            },
        }
    )
    device["control_enabled"] = True
    device["allowed_commands"] = ["set_state"]
    entities = entities_from_entry(device)
    assert [entity["metadata"]["endpoint"] for entity in entities] == ["left", "right"]
    assert len({entity["id"] for entity in entities}) == 2
    assert all("set_state" in {item["id"] for item in entity["available_commands"]} for entity in entities)
    assert "lock" not in {capability for entity in entities for capability in entity["capabilities"]}
    unsupported = next(item for item in device["exposes"] if item["property"] == "lock")
    assert unsupported["status"] == "unsupported"


def test_controls_require_runtime_enablement_and_allowlist() -> None:
    exposes = [{"capability": "state", "access": {"set": True}}]
    assert [item["id"] for item in available_commands_for(["state"], exposes, control_enabled=False)] == [
        "refresh"
    ]
    assert [
        item["id"]
        for item in available_commands_for(
            ["state"], exposes, control_enabled=True, allowed_commands=["set_state"]
        )
    ] == ["refresh", "set_state"]


@pytest.mark.anyio
async def test_publish_confirmation_distinguishes_acceptance_from_convergence(monkeypatch) -> None:
    client = Zigbee2MqttSidecarClient("http://sidecar")
    responses = iter(
        [
            {"sequence": 4, "messages": []},
            {"sequence": 5, "messages": [{"sequence": 5, "payload": {"state": "ON"}}]},
        ]
    )

    async def messages(*_args, **_kwargs):
        return next(responses)

    async def publish(*_args, **_kwargs):
        return {"ok": True, "status": "published"}

    monkeypatch.setattr(client, "mqtt_messages", messages)
    monkeypatch.setattr(client, "mqtt_publish", publish)
    result = await client.mqtt_publish_confirmed("zigbee2mqtt/lamp/set", {"state": "ON"})
    assert result["outcome"] == "device_state_converged"


def test_capability_catalog_never_marks_planned_or_excluded_available() -> None:
    path = Path(__file__).resolve().parents[1] / "capability-catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assert {row["status"] for row in catalog["capabilities"]} == {
        "implemented",
        "planned",
        "excluded",
    }


def test_subscription_configuration_persists_privately_for_restart(tmp_path, monkeypatch) -> None:
    target = tmp_path / "configs.json"
    monkeypatch.setenv("PIPHI_ZIGBEE_STATE_PATH", str(target))
    entries = {"device-1": {"config_id": "device-1", "mqtt_topic": "zigbee2mqtt/device-1"}}
    save_entries(entries)
    assert load_entries() == entries
    assert target.stat().st_mode & 0o777 == 0o600
