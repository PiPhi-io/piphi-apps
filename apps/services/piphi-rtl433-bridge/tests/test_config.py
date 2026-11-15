from piphi_rtl433_bridge.config import (
    build_bridge_config,
    build_model_packets_topic,
    build_packet_envelope,
    build_packets_topic,
    load_bridge_config,
    parse_extra_headers,
    parse_frequency_selection,
    parse_protocol_ids,
    reconfigure_bridge_config,
    resolve_frequency,
    validate_receiver_gain,
    validate_rtlsdr_device,
)
import pytest


def test_load_bridge_config_builds_validated_command_and_headers(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_FORWARD_ENABLED", "true")
    monkeypatch.setenv("RUNTIME_INGEST_URL", "http://runtime.test/ingest/rtl433")
    monkeypatch.setenv("BRIDGE_EXTRA_HEADERS_JSON", '{"X-Test": "true"}')
    monkeypatch.setenv("MQTT_ENABLED", "false")
    monkeypatch.setenv("MQTT_HOSTNAME", "mqtt.test")
    monkeypatch.setenv("MQTT_PORT", "1884")

    config = load_bridge_config()

    assert config.http_forward_enabled is True
    assert config.rtl433_command == ["rtl_433", "-F", "json", "-f", "433.92M"]
    assert config.runtime_ingest_url == "http://runtime.test/ingest/rtl433"
    assert config.extra_headers == {"X-Test": "true"}
    assert config.mqtt_enabled is False
    assert config.mqtt_hostname == "mqtt.test"
    assert config.mqtt_port == 1884


def test_load_bridge_config_builds_friendly_default_rtl433_command(monkeypatch) -> None:
    monkeypatch.delenv("RTL433_COMMAND", raising=False)

    config = load_bridge_config()

    assert config.radio_band == "433mhz"
    assert config.frequency == "433.92M"
    assert config.rtl433_command == ["rtl_433", "-F", "json", "-f", "433.92M"]


def test_load_bridge_config_supports_915mhz_preset(monkeypatch) -> None:
    monkeypatch.delenv("RTL433_COMMAND", raising=False)
    monkeypatch.setenv("RADIO_BAND", "915mhz")
    monkeypatch.setenv("RTLSDR_DEVICE", "1")
    monkeypatch.setenv("RECEIVER_GAIN", "32.8")
    monkeypatch.setenv("RTL433_PROTOCOLS", "40, 41")

    config = load_bridge_config()

    assert config.frequency == "915M"
    assert config.protocol_ids == ("40", "41")
    assert config.rtl433_command == [
        "rtl_433",
        "-F",
        "json",
        "-f",
        "915M",
        "-d",
        "1",
        "-g",
        "32.8",
        "-R",
        "40",
        "-R",
        "41",
    ]


def test_build_bridge_config_uses_explicit_values() -> None:
    config = build_bridge_config(
        http_forward_enabled=False,
        runtime_ingest_url="http://runtime.example/ingest/rtl433",
        forward_timeout_seconds=12.0,
        retry_delay_seconds=4.0,
        startup_delay_seconds=1.5,
        extra_headers_json='{"X-PiPhi":"bridge"}',
        extra_headers={"X-Env": "override"},
        mqtt_enabled=True,
        mqtt_hostname="mqtt.example",
        mqtt_port=2883,
        mqtt_client_id="bridge-1",
        mqtt_qos=1,
        mqtt_topic_root="piphi/sources/rtl433",
    )

    assert config.http_forward_enabled is False
    assert config.runtime_ingest_url == "http://runtime.example/ingest/rtl433"
    assert config.rtl433_command == ["rtl_433", "-F", "json", "-f", "433.92M"]
    assert config.extra_headers == {"X-PiPhi": "bridge", "X-Env": "override"}
    assert config.mqtt_enabled is True
    assert config.mqtt_hostname == "mqtt.example"
    assert config.mqtt_port == 2883
    assert config.mqtt_client_id == "bridge-1"
    assert config.mqtt_qos == 1


def test_build_bridge_config_uses_custom_frequency() -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.example/ingest/rtl433",
        radio_band="custom",
        custom_frequency="344.975M",
        forward_timeout_seconds=10.0,
        retry_delay_seconds=5.0,
        startup_delay_seconds=1.0,
    )

    assert config.frequency == "344.975M"
    assert config.rtl433_command == ["rtl_433", "-F", "json", "-f", "344.975M"]


def test_reconfigure_bridge_config_accepts_frequency_and_receiver() -> None:
    config = load_bridge_config()

    updated = reconfigure_bridge_config(
        config,
        frequency="915mhz",
        rtl_sdr_device="1",
        receiver_gain="32.8",
        protocol_ids_text="40,41",
    )

    assert updated.frequency == "915M"
    assert updated.rtl_sdr_device == "1"
    assert updated.rtl433_command == [
        "rtl_433", "-F", "json", "-f", "915M", "-d", "1", "-g", "32.8", "-R", "40", "-R", "41"
    ]


def test_parse_frequency_selection_treats_raw_frequency_as_custom() -> None:
    assert parse_frequency_selection("344.975M") == ("custom", "344.975M")


def test_command_is_always_built_from_validated_friendly_fields() -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.example/ingest/rtl433",
        radio_band="915mhz",
        forward_timeout_seconds=10.0,
        retry_delay_seconds=5.0,
        startup_delay_seconds=1.0,
    )

    assert config.frequency == "915M"
    assert config.rtl433_command == ["rtl_433", "-F", "json", "-f", "915M"]


def test_custom_frequency_requires_value() -> None:
    try:
        resolve_frequency(radio_band="custom")
    except ValueError as exc:
        assert "CUSTOM_FREQUENCY" in str(exc)
    else:
        raise AssertionError("Expected custom frequency validation error")


def test_parse_protocol_ids_accepts_commas_and_semicolons() -> None:
    assert parse_protocol_ids("40, 41; 42") == ("40", "41", "42")


def test_parse_extra_headers_returns_empty_dict_for_invalid_json() -> None:
    assert parse_extra_headers("{bad-json") == {}


def test_parse_extra_headers_returns_empty_dict_for_non_object_json() -> None:
    assert parse_extra_headers('["not", "an", "object"]') == {}


def test_build_packet_topics_and_envelope() -> None:
    assert build_packets_topic("piphi/sources/rtl433") == "piphi/sources/rtl433/packets"
    assert (
        build_model_packets_topic("piphi/sources/rtl433", "Nexus TH")
        == "piphi/sources/rtl433/models/Nexus_TH/packets"
    )

    envelope = build_packet_envelope(
        {
            "model": "Nexus-TH",
            "id": 42,
            "channel": 1,
        }
    )
    assert envelope["source"] == "rtl433"
    assert envelope["device_hint"]["id"] == "42"


def test_build_packet_envelope_uses_fallback_identity_fields() -> None:
    envelope = build_packet_envelope(
        {
            "model": "WeatherSensor",
            "device_id": "sensor-9",
            "subtype": "A",
        }
    )

    assert envelope["device_hint"]["id"] == "sensor-9"
    assert envelope["device_hint"]["channel"] == "A"


def test_build_model_packets_topic_sanitizes_slashes_and_spaces() -> None:
    assert (
        build_model_packets_topic("piphi/sources/rtl433", "Acurite / 5n1")
        == "piphi/sources/rtl433/models/Acurite___5n1/packets"
    )


def test_build_bridge_config_trims_trailing_slash_from_topic_root() -> None:
    config = build_bridge_config(
        http_forward_enabled=False,
        runtime_ingest_url="http://runtime.example/ingest/rtl433",
        forward_timeout_seconds=10.0,
        retry_delay_seconds=5.0,
        startup_delay_seconds=1.0,
        mqtt_enabled=True,
        mqtt_topic_root="piphi/sources/rtl433///",
    )

    assert config.mqtt_topic_root == "piphi/sources/rtl433"


def test_load_bridge_config_defaults_false_boolean_values(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_FORWARD_ENABLED", "off")
    monkeypatch.setenv("MQTT_ENABLED", "no")

    try:
        load_bridge_config()
    except ValueError as exc:
        assert "Exactly one authoritative forwarding transport" in str(exc)
    else:
        raise AssertionError("Expected a disabled transport configuration to be rejected")


def test_build_packet_envelope_uses_none_when_identity_fields_missing() -> None:
    envelope = build_packet_envelope({"model": "Unknown Sensor"})

    assert envelope["device_hint"]["id"] is None
    assert envelope["device_hint"]["channel"] is None


@pytest.mark.parametrize("frequency", ["19.9M", "1767M", "433.92;rm", "not-a-frequency"])
def test_custom_frequency_rejects_unsafe_or_out_of_range_values(frequency: str) -> None:
    with pytest.raises(ValueError, match="CUSTOM_FREQUENCY"):
        resolve_frequency(radio_band="custom", custom_frequency=frequency)


@pytest.mark.parametrize("selector", ["/dev/bus/usb", "rtl_tcp=host:1234", "32", "serial=x y"])
def test_receiver_selector_is_narrowly_validated(selector: str) -> None:
    with pytest.raises(ValueError, match="RTLSDR_DEVICE"):
        validate_rtlsdr_device(selector)


@pytest.mark.parametrize("gain", ["-1", "61", "nan", "very-high"])
def test_receiver_gain_is_bounded(gain: str) -> None:
    with pytest.raises(ValueError, match="RECEIVER_GAIN"):
        validate_receiver_gain(gain)


def test_protocol_ids_are_numeric_bounded_and_deduplicated() -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.test/ingest/rtl433",
        protocol_ids_text="1, 398, 1",
        forward_timeout_seconds=1,
        retry_delay_seconds=1,
        startup_delay_seconds=0,
    )
    assert config.protocol_ids == ("1", "398")

    with pytest.raises(ValueError, match="between 1 and 398"):
        build_bridge_config(
            http_forward_enabled=True,
            runtime_ingest_url="http://runtime.test/ingest/rtl433",
            protocol_ids_text="399",
            forward_timeout_seconds=1,
            retry_delay_seconds=1,
            startup_delay_seconds=0,
        )
