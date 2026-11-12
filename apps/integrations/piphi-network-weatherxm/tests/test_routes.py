from __future__ import annotations

from typing import Any

import httpx
import pytest

from piphi_network_weatherxm.main import app
from piphi_network_weatherxm.routes import commands as command_routes
from piphi_network_weatherxm.routes import discovery as discovery_routes
from piphi_network_weatherxm.routes import telemetry as telemetry_routes
from piphi_network_weatherxm.state import registry


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def clear_registry() -> None:
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


async def configure_placeholder_station(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post(
        "/config",
        json={
            "id": "weatherxm-station",
            "station_id": "station-1",
            "alias": "Backyard",
            "api_token": "change-me",
        },
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_ui_config_exposes_weatherxm_station_credentials(client: httpx.AsyncClient) -> None:
    response = await client.get("/ui-config")

    body = response.json()
    assert response.status_code == 200
    assert "station_id" in body["schema"]["required"]
    assert "api_token" in body["schema"]["properties"]
    assert body["uiSchema"]["password"]["ui:widget"] == "password"


@pytest.mark.anyio
async def test_config_with_placeholder_credentials_records_disconnected_state(client: httpx.AsyncClient) -> None:
    await configure_placeholder_station(client)

    state = (await client.get("/state")).json()
    snapshot = state["state_snapshots"]["weatherxm-station"]["state"]
    assert snapshot["connected"] is False
    assert snapshot["reason"] == "missing_weatherxm_credentials"
    assert snapshot["station_id"] == "station-1"


@pytest.mark.anyio
async def test_entities_reflect_configured_station_alias(client: httpx.AsyncClient) -> None:
    await configure_placeholder_station(client)

    body = (await client.get("/entities")).json()

    assert body["entities"][0]["id"] == "weatherxm-station"
    assert body["entities"][0]["name"] == "Backyard"
    assert "humidity_percent" in body["entities"][0]["capabilities"]


@pytest.mark.anyio
async def test_discover_without_credentials_returns_manual_station_candidate(client: httpx.AsyncClient) -> None:
    response = await client.post("/discover", json={"inputs": {"station_id": "station-1", "alias": "Backyard"}})

    body = response.json()
    assert response.status_code == 200
    assert "station-1" in str(body)
    assert "Backyard" in str(body)


@pytest.mark.anyio
async def test_discover_with_credentials_returns_account_devices(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeWeatherXMClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def devices(self) -> list[dict[str, Any]]:
            return [{"id": "station-1", "label": "Roof", "relation": "owned", "timezone": "America/New_York"}]

    monkeypatch.setattr(discovery_routes, "WeatherXMClient", FakeWeatherXMClient)

    response = await client.post("/discover", json={"inputs": {"api_token": "token"}})

    body = response.json()
    assert response.status_code == 200
    assert "station-1" in str(body)
    assert "Roof" in str(body)
    assert "America/New_York" in str(body)


@pytest.mark.anyio
async def test_command_requires_command_name(client: httpx.AsyncClient) -> None:
    response = await client.post("/command", json={})

    assert response.status_code == 400
    assert "Missing command" in response.text


@pytest.mark.anyio
async def test_command_rejects_unsupported_command(client: httpx.AsyncClient) -> None:
    response = await client.post("/command", json={"command": "reboot"})

    assert response.status_code == 400
    assert "Unsupported command" in response.text


@pytest.mark.anyio
async def test_refresh_command_without_config_records_event_but_does_not_refresh(client: httpx.AsyncClient) -> None:
    response = await client.post("/command", json={"command": "refresh", "device_id": "station-1"})

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["state"] is None


@pytest.mark.anyio
async def test_refresh_command_refreshes_configured_station(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await configure_placeholder_station(client)
    refreshes = 0

    async def fake_refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
        nonlocal refreshes
        refreshes += 1
        return {"station_id": entry["station_id"], "temperature_c": 22.0}

    monkeypatch.setattr(command_routes, "refresh_entry", fake_refresh_entry)

    headers = {"X-PiPhi-Idempotency-Key": "weatherxm-refresh-idempotency-1"}
    response = await client.post(
        "/command",
        json={"command": "refresh", "device_id": "weatherxm-station", "config_id": "weatherxm-station"},
        headers=headers,
    )
    replay = await client.post(
        "/command",
        json={"command": "refresh", "device_id": "weatherxm-station", "config_id": "weatherxm-station"},
        headers=headers,
    )

    assert response.status_code == 200
    assert replay.status_code == 200
    assert response.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert refreshes == 1
    assert response.json()["state"] == {"station_id": "station-1", "temperature_c": 22.0}


@pytest.mark.anyio
async def test_refresh_command_accepts_automation_runtime_contract(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await configure_placeholder_station(client)

    async def fake_refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
        return {"station_id": entry["station_id"], "temperature_c": 22.0}

    monkeypatch.setattr(command_routes, "refresh_entry", fake_refresh_entry)

    response = await client.post(
        "/command",
        json={
            "contract_version": "automation.runtime.command.v1",
            "command": "refresh_readings",
            "target": {
                "config_id": "weatherxm-station",
                "device_id": "weatherxm-station",
            },
            "params": {"force": True},
            "capability": "device.refresh",
            "capability_requirements": ["device.refresh"],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["command"] == "refresh"
    assert body["contract_version"] == "automation.runtime.command.v1"
    assert body["config_id"] == "weatherxm-station"
    assert body["params"] == {"force": True}
    assert body["state"] == {"station_id": "station-1", "temperature_c": 22.0}


@pytest.mark.anyio
async def test_command_rejects_unsupported_capability(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/command",
        json={
            "command": "refresh",
            "target": {"device_id": "weatherxm-station"},
            "capability": "switch.power",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "unsupported_capability"


@pytest.mark.anyio
async def test_sync_cloud_command_refreshes_all_entries(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await configure_placeholder_station(client)

    async def fake_refresh_all_entries() -> list[dict[str, Any]]:
        return [{"station_id": "station-1", "humidity_percent": 55}]

    monkeypatch.setattr(command_routes, "refresh_all_entries", fake_refresh_all_entries)

    response = await client.post("/command", json={"command": "sync_cloud", "device_id": "weatherxm-station"})

    assert response.status_code == 200
    assert response.json()["state"] == [{"station_id": "station-1", "humidity_percent": 55}]


@pytest.mark.anyio
async def test_telemetry_example_without_config_reports_no_configured_devices(client: httpx.AsyncClient) -> None:
    response = await client.post("/telemetry/example")

    assert response.status_code == 200
    assert response.json() == {"ok": False, "reason": "no configured devices"}


@pytest.mark.anyio
async def test_telemetry_for_missing_config_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/telemetry/device/missing/example")

    assert response.status_code == 404
    assert "unknown config_id=missing" in response.text


@pytest.mark.anyio
async def test_telemetry_example_schedules_latest_metrics(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await configure_placeholder_station(client)
    captured: dict[str, Any] = {}

    async def fake_refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
        entry["latest_metrics"] = {"connected": True, "temperature_c": 23.5}
        entry["latest_units"] = {"connected": "bool", "temperature_c": "C"}
        return entry["latest_metrics"]

    def fake_schedule_telemetry_delivery(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(telemetry_routes, "refresh_entry", fake_refresh_entry)
    monkeypatch.setattr(telemetry_routes, "schedule_telemetry_delivery", fake_schedule_telemetry_delivery)

    response = await client.post("/telemetry/example")

    assert response.status_code == 200
    assert response.json() == {"status": "queued"}
    assert captured["metrics"] == {"connected": True, "temperature_c": 23.5}
    assert captured["units"] == {"connected": "bool", "temperature_c": "C"}


@pytest.mark.anyio
async def test_state_summary_counts_entries_and_events(client: httpx.AsyncClient) -> None:
    await configure_placeholder_station(client)
    await client.post("/command", json={"command": "refresh", "device_id": "weatherxm-station"})

    body = (await client.get("/state")).json()

    assert body["summary"]["active_config_count"] == 1
    assert body["summary"]["recent_event_count"] >= 1


@pytest.mark.anyio
async def test_contract_reports_weatherxm_runtime_metadata(client: httpx.AsyncClient) -> None:
    body = (await client.get("/contract")).json()

    assert body["integration_id"] == "piphi-network-weatherxm"
    assert body["name"] == "PiPhi Network WeatherXM"
    assert body["preset"] == "cloud-polling-api"
    assert body["domain"] == "cloud-api"
