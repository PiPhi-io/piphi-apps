from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from piphi_network_waste_collection import state
from piphi_network_waste_collection.contract import CONFIG_SCHEMA
from piphi_network_waste_collection.manual_schedule import resolve_manual_pickup
from piphi_network_waste_collection.routes.discovery import discover
from piphi_network_waste_collection.routes.entities import entities
from piphi_network_waste_collection.schemas import DeviceConfig

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)


def test_manual_pickup_countdown_respects_timezone_and_today() -> None:
    pickup = resolve_manual_pickup(
        "2026-09-20", "Recycling", "America/Los_Angeles", now=NOW
    )
    assert pickup.collection_type == "Recycling"
    assert pickup.collection_date == "2026-09-20"
    assert pickup.days_until_collection == 1
    today = resolve_manual_pickup("2026-09-19", "Waste", now=NOW)
    assert today.days_until_collection == 0


def test_invalid_or_expired_manual_dates_do_not_show_as_live() -> None:
    for date, kind, zone in (
        ("2026-09-18", "Waste", "UTC"),
        ("20260920", "Waste", "UTC"),
        ("2026-09-20", "", "UTC"),
        ("2026-09-20", "Waste", "Not/A_Timezone"),
    ):
        with pytest.raises(ValueError):
            resolve_manual_pickup(date, kind, zone, now=NOW)


@pytest.mark.anyio
async def test_runtime_publishes_user_supplied_date_not_provider_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[dict] = []
    monkeypatch.setattr(
        state, "schedule_telemetry_delivery", lambda **kwargs: delivered.append(kwargs)
    )
    config = DeviceConfig(
        id="manual-collection-test",
        next_collection_date="2099-01-01",
        collection_type="Recycling",
        api_key="ignored-secret",
    )
    entry = state.make_entry(config)
    state.registry.set(entry["config_id"], entry)
    try:
        result = await state.refresh_entry(entry)
        assert result["connected"] is True
        assert result["next_collection_type"] == "Recycling"
        assert result["days_until_collection"] > 0
        assert delivered[0]["metrics"]["next_collection_date"] == "2099-01-01"
        assert "ignored-secret" not in json.dumps(entry)
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_missing_manual_date_fails_closed() -> None:
    config = DeviceConfig(id="manual-missing-test")
    entry = state.make_entry(config)
    state.registry.set(entry["config_id"], entry)
    try:
        assert await state.refresh_entry(entry) == {
            "connected": False,
            "reason": "manual_schedule_unavailable",
        }
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_unconfigured_schedule_does_not_advertise_demo_device() -> None:
    assert not (await discover()).devices
    assert "demo-device" not in json.dumps(await entities())


def test_setup_and_widget_only_expose_manual_schedule() -> None:
    schema = CONFIG_SCHEMA["schema"]
    assert schema["required"] == ["next_collection_date", "collection_type"]
    assert not {"host", "api_key", "base_url"} & set(schema["properties"])
    manifest = json.loads((ROOT / "manifest.json").read_text())
    package = json.loads((ROOT / "experiences/next/package.source.json").read_text())
    assert manifest["ui"]["experience_packages"][0]["registry_id"] == (
        "io.piphi.waste-next-collection"
    )
    assert package["owning_integration_id"] == manifest["id"]
    (widget,) = package["widgets"]
    assert {slot["capability_requirements"][0] for slot in widget["binding_slots"]} == {
        "days_until_collection",
        "next_collection_type",
    }
