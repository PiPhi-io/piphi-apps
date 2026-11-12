from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from piphi_network_octopus_energy import state
from piphi_network_octopus_energy.contract import CONFIG_SCHEMA
from piphi_network_octopus_energy.routes.discovery import discover
from piphi_network_octopus_energy.routes.entities import entities
from piphi_network_octopus_energy.schemas import DeviceConfig
from piphi_network_octopus_energy.tariffs import TariffRates, fetch_rates, parse_rates

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 19, 12, 15, tzinfo=UTC)


def _row(start: str, end: str | None, price: float, method: str | None = None) -> dict:
    return {
        "valid_from": start,
        "valid_to": end,
        "value_inc_vat": price,
        "payment_method": method,
    }


def test_rate_selection_uses_validity_and_prefers_direct_debit() -> None:
    payload = {
        "results": [
            _row("2026-09-19T12:30Z", "2026-09-19T13:00Z", 9.1),
            _row("2026-09-19T12:00Z", "2026-09-19T12:30Z", 20.0, "NON_DIRECT_DEBIT"),
            _row("2026-09-19T12:00Z", "2026-09-19T12:30Z", -2.5, "DIRECT_DEBIT"),
            _row("2026-09-19T11:30Z", "2026-09-19T12:00Z", 18.0),
        ]
    }
    rates = parse_rates(payload, now=NOW)
    assert rates.current_p_kwh == -2.5
    assert rates.next_p_kwh == 9.1
    assert rates.current_valid_to == "2026-09-19T12:30:00+00:00"


def test_rate_parser_rejects_missing_or_malformed_active_values() -> None:
    with pytest.raises(TypeError, match="no results"):
        parse_rates({}, now=NOW)
    with pytest.raises(ValueError, match="No current"):
        parse_rates(
            {"results": [_row("2026-09-19T12:00Z", None, float("nan"))]}, now=NOW
        )


@pytest.mark.anyio
async def test_fetch_uses_fixed_https_origin_and_bounded_public_endpoint() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    _row("2026-09-19T12:00Z", "2026-09-19T12:30Z", 18.4),
                ]
            },
        )

    rates = await fetch_rates(
        "agile-flex-22-11-25",
        "E-1R-AGILE-FLEX-22-11-25-A",
        now=NOW,
        transport=httpx.MockTransport(respond),
    )
    assert rates.current_p_kwh == 18.4
    assert rates.next_p_kwh is None
    assert seen[0].url.host == "api.octopus.energy"
    assert seen[0].url.path.endswith(
        "/products/AGILE-FLEX-22-11-25/electricity-tariffs/"
        "E-1R-AGILE-FLEX-22-11-25-A/standard-unit-rates/"
    )
    assert seen[0].url.params["page_size"] == "100"
    with pytest.raises(ValueError, match="Invalid Octopus"):
        await fetch_rates(
            "../other", "unsafe", now=NOW, transport=httpx.MockTransport(respond)
        )
    assert len(seen) == 1


@pytest.mark.anyio
async def test_runtime_publishes_real_rates_and_never_exposes_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*_args: object) -> TariffRates:
        return TariffRates(12.3, 9.4, "2026-09-19T12:30:00+00:00")

    delivered: list[dict] = []
    monkeypatch.setattr(state, "fetch_rates", fake_fetch)
    monkeypatch.setattr(
        state, "schedule_telemetry_delivery", lambda **kwargs: delivered.append(kwargs)
    )
    config = DeviceConfig(
        id="octopus-widget-test",
        host="home-tariff",
        api_key="should-never-leak",
        product_code="AGILE-FLEX-22-11-25",
        tariff_code="E-1R-AGILE-FLEX-22-11-25-A",
    )
    entry = state.make_entry(config)
    state.registry.set(config.id, entry)
    try:
        result = await state.refresh_entry(entry)
        assert result["current_rate"] == 12.3
        assert result["next_rate"] == 9.4
        assert delivered[0]["metrics"]["current_rate"] == 12.3
        assert delivered[0]["units"]["current_rate"] == "p/kWh"
        assert "should-never-leak" not in json.dumps(entry)
        assert "should-never-leak" not in json.dumps(result)
    finally:
        state.registry.remove(config.id)


@pytest.mark.anyio
async def test_runtime_fails_closed_when_tariff_is_missing_or_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*_args: object) -> TariffRates:
        raise ValueError("vendor payload with secret")

    monkeypatch.setattr(state, "fetch_rates", unavailable)
    config = DeviceConfig(id="octopus-error-test", host="home-tariff")
    entry = state.make_entry(config)
    state.registry.set(config.id, entry)
    try:
        assert (await state.refresh_entry(entry))["reason"] == "missing_tariff_codes"
        entry["config"].update(
            {
                "product_code": "AGILE-FLEX-22-11-25",
                "tariff_code": "E-1R-AGILE-FLEX-22-11-25-A",
            }
        )
        result = await state.refresh_entry(entry)
        assert result == {"connected": False, "reason": "tariff_fetch_failed"}
        assert "vendor payload" not in json.dumps(result)
    finally:
        state.registry.remove(config.id)


def test_widget_tracks_real_tariff_capabilities() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    package = json.loads((ROOT / "experiences/rates/package.source.json").read_text())
    assert (
        manifest["ui"]["experience_packages"][0]["registry_id"]
        == "io.piphi.octopus-rates"
    )
    assert package["owning_integration_id"] == manifest["id"]
    (widget,) = package["widgets"]
    assert widget["runtime"] == "declarative"
    assert {slot["capability_requirements"][0] for slot in widget["binding_slots"]} == {
        "current_rate",
        "next_rate",
    }
    assert {item["slot_id"] for item in widget["recipe"]["items"]} == {
        slot["id"] for slot in widget["binding_slots"]
    }


@pytest.mark.anyio
async def test_unconfigured_tariff_does_not_advertise_demo_device() -> None:
    discovery = await discover()
    runtime_entities = await entities()
    assert not discovery.devices
    assert "demo-device" not in json.dumps(runtime_entities)


def test_tariff_setup_only_requests_relevant_fields() -> None:
    schema = CONFIG_SCHEMA["schema"]
    assert schema["required"] == ["product_code", "tariff_code"]
    assert not {"host", "base_url", "api_key"} & set(schema["properties"])
