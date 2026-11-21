from piphi_network_433mhz.profiles import (
    _copy_first_present,
    _copy_if_present,
    _safe_metric_value,
    _strict_bool,
    build_entities,
    extract_metrics,
    format_capability_name,
    infer_profile_id,
    metric_units,
    normalize_metric_key,
    normalize_profile_id,
)


def test_infer_weather_profile_from_packet_fields() -> None:
    profile_id = infer_profile_id(
        {
            "model": "Acurite-Tower",
            "id": 42,
            "temperature_C": 21.5,
            "humidity": 48,
        }
    )

    assert profile_id == "weather_basic"


def test_extract_contact_metrics() -> None:
    metrics = extract_metrics(
        {
            "model": "Generic-Contact",
            "id": 7,
            "state": "open",
            "battery_ok": 1,
        },
        "contact_sensor",
    )

    assert metrics["contact_open"] is True
    assert metrics["battery_ok"] == 1


def test_infer_leak_profile_from_packet_fields() -> None:
    profile_id = infer_profile_id(
        {
            "model": "Leak-Sensor",
            "id": 9,
            "water": 1,
        }
    )

    assert profile_id == "leak_sensor"


def test_extract_weather_metrics_prefers_first_matching_fields() -> None:
    metrics = extract_metrics(
        {
            "model": "Weather",
            "id": 1,
            "temperature_C": 21.5,
            "humidity": 48,
            "wind_avg_km_h": 12.0,
            "wind_speed_km_h": 99.0,
            "rain_mm": 4.2,
            "battery_ok": 1,
            "rssi": -70,
            "pressure_hPa": 1009.8,
            "unknown1": 99,
        },
        "weather_basic",
    )

    assert metrics["temperature_c"] == 21.5
    assert metrics["humidity_percent"] == 48
    assert metrics["wind_speed_kph"] == 12.0
    assert metrics["rain_total_mm"] == 4.2
    assert metrics["signal_rssi"] == -70
    assert metrics["pressure_hpa"] == 1009.8
    assert "unknown1" not in metrics
    assert "id" not in metrics


def test_normalize_profile_id_falls_back_for_unknown_values() -> None:
    assert normalize_profile_id("not-a-real-profile") == "auto"
    assert normalize_profile_id(None) == "auto"


def test_build_entities_and_metric_units_follow_profile_definition() -> None:
    entities = build_entities(
        device_name="Garage Sensor",
        device_key="garage::1::na",
        profile_id="contact_sensor",
    )
    units = metric_units("weather_basic", ["temperature_c", "humidity_percent", "unknown"])

    assert entities[0]["id"] == "garage::1::na.contact_open"
    assert entities[0]["name"] == "Garage Sensor Contact Open"
    assert units == {
        "temperature_c": "C",
        "humidity_percent": "%",
    }


def test_format_capability_name_title_cases_words() -> None:
    assert format_capability_name("rain_total_mm") == "Rain Total Mm"


def test_signal_metrics_preserve_rssi_snr_and_noise_semantics() -> None:
    metrics = extract_metrics(
        {"model": "Weather", "id": 1, "rssi": -72, "snr": 8.5, "noise": -91},
        "generic_sensor",
    )

    assert metrics == {"signal_rssi": -72, "signal_snr": 8.5, "signal_noise": -91}
    assert metric_units("generic_sensor", list(metrics)) == {
        "signal_rssi": "dBm",
        "signal_snr": "dB",
        "signal_noise": "dB",
    }


def test_unknown_and_out_of_range_fields_are_not_product_metrics() -> None:
    metrics = extract_metrics(
        {
            "model": "Unqualified",
            "id": 9,
            "temperature_C": 800,
            "humidity": -1,
            "battery_ok": 7,
            "tamper": 1,
            "energy_kWh": 12.5,
        },
        "generic_sensor",
    )

    assert metrics == {}


def test_direct_contact_leak_and_boolean_variants_are_strict() -> None:
    metrics = extract_metrics(
        {
            "contact_open": "closed",
            "leak": "wet",
            "battery_ok": False,
        },
        "generic_sensor",
    )
    assert metrics == {
        "contact_open": False,
        "leak_detected": True,
        "battery_ok": False,
    }
    assert infer_profile_id({"contact_open": True}) == "contact_sensor"
    assert _strict_bool(True) is True
    assert _strict_bool(2) is None
    assert _strict_bool("dry") is False
    assert _strict_bool("maybe") is None


def test_metric_normalization_and_copy_helpers_reject_identity_and_unsafe_values() -> None:
    metrics = {}
    consumed = set()
    packet = {"first": None, "second": 3, "present": "value"}
    _copy_if_present(metrics, packet, "present", "copied", consumed)
    _copy_first_present(metrics, packet, ("first", "second"), "selected", consumed)
    assert metrics == {"copied": "value", "selected": 3}
    assert consumed == {"present", "second"}
    assert normalize_metric_key("Temperature C") == "temperature_c"
    assert normalize_metric_key("device_id") is None
    assert normalize_metric_key("debug_flags") is None
    assert _safe_metric_value(1.5) == 1.5
    assert _safe_metric_value(True) is True
    assert _safe_metric_value("unsafe") is None
