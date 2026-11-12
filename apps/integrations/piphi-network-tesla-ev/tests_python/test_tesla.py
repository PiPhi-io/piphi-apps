from __future__ import annotations

import importlib
from typing import Any

import httpx
import pytest

from piphi_network_tesla_ev import app, create_app
from piphi_network_tesla_ev.tesla import (
    TeslaAPIError,
    TeslaClient,
    normalize_summary_state,
    normalize_vehicle_data_state,
    resolve_fleet_api_base_url,
    telemetry_metrics,
)

app_module = importlib.import_module("piphi_network_tesla_ev.app")


VIN = "5YJ3E1EA7LF000000"


class FakeTeslaClient:
    calls: list[tuple[str, str]] = []

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def list_vehicles(self) -> list[dict[str, Any]]:
        self.calls.append(("list", VIN))
        return [{"id": 1, "vehicle_id": 2, "vin": VIN, "display_name": "Model 3", "state": "online", "in_service": False}]

    async def vehicle_summary(self, vin: str) -> dict[str, Any]:
        self.calls.append(("summary", vin))
        return {"id": 1, "vehicle_id": 2, "vin": vin, "display_name": "Model 3", "state": "online", "in_service": False}

    async def vehicle_data(self, vin: str) -> dict[str, Any]:
        self.calls.append(("data", vin))
        return {
            "state": "online",
            "charge_state": {
                "battery_level": 72,
                "usable_battery_level": 70,
                "charging_state": "Charging",
                "charge_limit_soc": 80,
                "time_to_full_charge": 1.5,
                "charger_power": 11,
                "battery_range": 220.5,
                "charger_actual_current": 32,
                "charge_energy_added": 4.2,
                "conn_charge_cable": "IEC",
            },
            "climate_state": {"inside_temp": 21.5, "outside_temp": 18.0, "is_climate_on": True},
            "drive_state": {"speed": 0, "latitude": 33.4, "longitude": -84.4, "heading": 180, "shift_state": "P"},
            "vehicle_state": {"locked": True, "odometer": 12345.6},
        }

    async def wake(self, vin: str) -> dict[str, Any]:
        self.calls.append(("wake", vin))
        return {"id": 1, "vehicle_id": 2, "vin": vin, "display_name": "Model 3", "state": "online", "in_service": False}


async def _noop_telemetry(_entry: dict[str, Any], _state: dict[str, Any]) -> None:
    return None


@pytest.fixture(autouse=True)
def reset_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    app_module.registry.entries.clear()
    app_module.registry.state_snapshots.clear()
    app_module.registry.recent_events.clear()
    FakeTeslaClient.calls.clear()
    monkeypatch.setattr(app_module, "TeslaClient", FakeTeslaClient)
    monkeypatch.setattr(app_module, "_client", lambda _config: FakeTeslaClient())
    monkeypatch.setattr(app_module, "deliver_telemetry", _noop_telemetry)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as value:
        yield value


def config_payload(**updates: Any) -> dict[str, Any]:
    return {
        "id": "cfg-tesla-1",
        "vin": VIN,
        "access_token": "test-token",
        "region": "na",
        "include_location": True,
        **updates,
    }


def test_package_exports_fastapi_app() -> None:
    assert app.title == "PiPhi Network Tesla EV"
    assert create_app is not None


@pytest.mark.anyio
async def test_health_ui_manifest_and_empty_state(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).status_code == 200
    ui = (await client.get("/ui-config")).json()
    assert "vin" in ui["schema"]["required"]
    assert ui["uiSchema"]["access_token"]["ui:widget"] == "password"
    manifest = (await client.get("/manifest.json")).json()
    assert manifest["id"] == "piphi-network-tesla-ev"
    assert (await client.get("/state")).json()["summary"]["activeConfigCount"] == 0


@pytest.mark.anyio
async def test_discovery_get_and_post_preserve_contract(client: httpx.AsyncClient) -> None:
    assert (await client.get("/discover")).status_code == 400
    responses = [
        await client.get("/discover", params={"access_token": "token", "region": "na"}),
        await client.post("/discovery", json={"inputs": {"access_token": "token", "region": "na"}}),
    ]
    for response in responses:
        assert response.status_code == 200
        device = response.json()["devices"][0]
        assert device["id"] == VIN
        assert device["suggested_config"] == {"vin": VIN, "region": "na"}


@pytest.mark.anyio
async def test_config_refresh_state_entities_and_deconfigure(client: httpx.AsyncClient) -> None:
    configured = await client.post("/config", json=config_payload(container_id="container-1"))
    assert configured.status_code == 200
    assert configured.json()["config_id"] == "cfg-tesla-1"
    latest = (await client.get("/state")).json()["entries"]["cfg-tesla-1"]["latest_state"]
    assert latest["batteryLevel"] == 72
    assert latest["chargingState"] == "Charging"
    entity = (await client.get("/entities")).json()["entities"][0]
    assert entity["deviceId"] == VIN
    assert "latitude" in entity["capabilities"]
    removed = await client.post("/deconfigure", json={"config_id": "cfg-tesla-1"})
    assert removed.status_code == 200
    assert removed.json()["removed"] is True


@pytest.mark.anyio
async def test_config_validation_and_location_filter(client: httpx.AsyncClient) -> None:
    assert (await client.post("/config", json=config_payload(vin=""))).status_code == 400
    assert (await client.post("/config", json=config_payload(access_token=""))).status_code == 400
    await client.post("/config", json=config_payload(include_location=False))
    entity = (await client.get("/entities")).json()["entities"][0]
    assert "latitude" not in entity["capabilities"]
    metrics, units = telemetry_metrics(app_module.registry.get("cfg-tesla-1")["latest_state"])
    assert "latitude" not in metrics
    assert "latitude" not in units


@pytest.mark.anyio
async def test_config_sync_replaces_snapshot(client: httpx.AsyncClient) -> None:
    await client.post("/config", json=config_payload(id="stale", configId="stale"))
    response = await client.post(
        "/configs/sync",
        json={"generation": 4, "configs": [config_payload(id="fresh", configId="fresh")]},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["generation"] == 4
    assert body["applied_config_ids"] == ["fresh"]
    assert body["removed_config_ids"] == ["stale"]


@pytest.mark.anyio
async def test_refresh_command_is_durably_idempotent(client: httpx.AsyncClient) -> None:
    await client.post("/config", json=config_payload())
    FakeTeslaClient.calls.clear()
    headers = {"X-PiPhi-Idempotency-Key": "tesla-refresh-python-1"}
    payload = {
        "contract_version": "automation.runtime.command.v1",
        "command": "refresh_readings",
        "target": {"config_id": "cfg-tesla-1", "device_id": VIN},
        "capability": "device.refresh",
        "capability_requirements": ["device.refresh"],
        "params": {"force": True},
    }
    first = await client.post("/command", json=payload, headers=headers)
    replay = await client.post("/command", json=payload, headers=headers)
    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert FakeTeslaClient.calls.count(("summary", VIN)) == 1
    assert FakeTeslaClient.calls.count(("data", VIN)) == 1


@pytest.mark.anyio
async def test_wake_command_is_durably_idempotent(client: httpx.AsyncClient) -> None:
    await client.post("/config", json=config_payload())
    FakeTeslaClient.calls.clear()
    headers = {"X-PiPhi-Idempotency-Key": "tesla-wake-python-1"}
    payload = {"command": "wake_up", "config_id": "cfg-tesla-1", "capability": "tesla.wake"}
    first = await client.post("/command", json=payload, headers=headers)
    replay = await client.post("/command", json=payload, headers=headers)
    assert first.status_code == 200
    assert replay.json()["replayed"] is True
    assert FakeTeslaClient.calls == [("wake", VIN)]
    assert first.json()["state"]["lastCommandAt"]


@pytest.mark.anyio
async def test_command_validation(client: httpx.AsyncClient) -> None:
    await client.post("/config", json=config_payload())
    assert (await client.post("/command", json={})).status_code == 400
    assert (await client.post("/command", json={"command": "unlock"})).status_code == 400
    unsupported = await client.post("/command", json={"command": "refresh", "capability": "lock.unlock"})
    assert unsupported.status_code == 400


def test_normalization() -> None:
    config = {"configId": "cfg", "vin": VIN, "region": "na", "include_location": True}
    summary = {"vin": VIN, "display_name": "Model 3", "state": "online", "in_service": False}
    assert normalize_summary_state(config, summary)["online"] is True
    detailed = normalize_vehicle_data_state(
        config,
        summary,
        {"charge_state": {"charging_state": "Disconnected"}, "drive_state": {"latitude": 1.2}},
    )
    assert detailed["pluggedIn"] is False
    assert detailed["latitude"] == 1.2
    assert resolve_fleet_api_base_url("eu").endswith("tesla.com")


@pytest.mark.anyio
async def test_tesla_client_rejects_error_and_missing_envelopes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/vehicles"):
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(200, json={"unexpected": True})

    client = TeslaClient("token", transport=httpx.MockTransport(handler))
    with pytest.raises(TeslaAPIError, match="unauthorized"):
        await client.list_vehicles()
    with pytest.raises(TeslaAPIError, match="missing a response"):
        await client.vehicle_summary(VIN)
