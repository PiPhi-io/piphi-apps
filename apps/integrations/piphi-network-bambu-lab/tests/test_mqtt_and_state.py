from __future__ import annotations

import asyncio
import json
import ssl
from types import SimpleNamespace

import pytest

from piphi_network_bambu_lab import state
from piphi_network_bambu_lab.mqtt_client import MAX_REPORT_BYTES, PrinterMqttSession
from piphi_network_bambu_lab.schemas import DeviceConfig


def test_config_requires_private_lan_and_explicit_developer_mode() -> None:
    base = {"id": "printer-test", "host": "192.168.1.50", "serial": "abc123456", "access_code": "secretcode", "developer_mode_acknowledged": True}
    config = DeviceConfig.model_validate(base)
    assert config.serial == "ABC123456"
    assert "secretcode" not in repr(config)
    for bad in ({**base, "host": "8.8.8.8"}, {**base, "host": "127.0.0.1"}, {**base, "developer_mode_acknowledged": False}):
        with pytest.raises(ValueError):
            DeviceConfig.model_validate(bad)


def test_certificate_requires_exact_configured_serial() -> None:
    session = PrinterMqttSession(host="192.168.1.50", serial="ABC123456", access_code="secretcode", on_report=lambda _: None, on_offline=lambda: None)
    good = SimpleNamespace(getpeercert=lambda: {"subject": ((('commonName', 'ABC123456'),),)})
    bad = SimpleNamespace(getpeercert=lambda: {"subject": ((('commonName', 'OTHER'),),)})
    session.verify_socket(good)
    with pytest.raises(ssl.CertificateError):
        session.verify_socket(bad)


def test_mqtt_filters_topics_payloads_and_rate_limits_refresh(monkeypatch) -> None:
    reports = []
    session = PrinterMqttSession(host="192.168.1.50", serial="ABC123456", access_code="secretcode", on_report=reports.append, on_offline=lambda: None)
    session._handle_message(None, None, SimpleNamespace(topic="other", payload=b'{}'))
    session._handle_message(None, None, SimpleNamespace(topic=session.report_topic, payload=b"not json"))
    session._handle_message(None, None, SimpleNamespace(topic=session.report_topic, payload=b"x" * (MAX_REPORT_BYTES + 1)))
    assert reports == []
    payload = {"print": {"command": "push_status", "gcode_state": "RUNNING"}}
    session._handle_message(None, None, SimpleNamespace(topic=session.report_topic, payload=json.dumps(payload).encode()))
    assert reports == [payload]
    published = []
    session._client = SimpleNamespace(publish=lambda *args, **kwargs: published.append((args, kwargs)) or SimpleNamespace(rc=0))
    session.connected = True
    monkeypatch.setattr("piphi_network_bambu_lab.mqtt_client.monotonic", lambda: 10)
    assert session.request_full_status() is True
    assert session.request_full_status() is False
    assert len(published) == 1
    assert published[0][0][0] == session.request_topic
    assert json.loads(published[0][0][1])["pushing"]["command"] == "pushall"


def test_paho_session_sets_tls_and_serial_check_before_connect(monkeypatch) -> None:
    mqtt = pytest.importorskip("paho.mqtt.client")
    calls = []
    monkeypatch.setattr(mqtt.Client, "connect_async", lambda self, *args, **kwargs: calls.append(("connect", args)))
    monkeypatch.setattr(mqtt.Client, "loop_start", lambda self: calls.append(("loop",)))
    session = PrinterMqttSession(host="192.168.1.50", serial="ABC123456", access_code="secretcode", on_report=lambda _: None, on_offline=lambda: None)
    session.start()
    assert session._client._ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert session._client._ssl_context.check_hostname is False
    assert session._client.suppress_exceptions is False
    assert callable(session._client.on_socket_open)
    bad_peer = SimpleNamespace(getpeercert=lambda: {"subject": ((('commonName', 'OTHER'),),)})
    with pytest.raises(ssl.CertificateError):
        session._client.on_socket_open(session._client, None, bad_peer)
    assert calls == [("connect", ("192.168.1.50", 8883)), ("loop",)]


@pytest.mark.anyio
async def test_real_report_and_disconnect_update_state_without_secrets(mock_mqtt, monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: sent.append(kwargs))
    config = DeviceConfig.model_validate({"id": "report-test", "host": "192.168.1.50", "serial": "ABC123456", "access_code": "secretcode", "developer_mode_acknowledged": True})
    try:
        await state.apply_config(config)
        assert state.current_state(config.id)["connected"] is False
        assert "secretcode" not in str(state.registry.entries)
        assert "ABC123456" not in str(state.registry.entries)
        await state.record_report(config.id, {"print": {"command": "push_status", "gcode_state": "RUNNING", "mc_percent": 62, "gcode_file": "private-file.3mf"}})
        assert state.current_state(config.id)["print_progress_percent"] == 62
        assert state.current_state(config.id)["connected"] is True
        assert "private-file.3mf" not in str(state.registry.state_snapshots)
        assert sent[-1]["metrics"]["print_progress_percent"] == 62
        await state.mark_offline(config.id)
        assert state.current_state(config.id)["connected"] is False
        assert config.id not in state._reports
    finally:
        await state.remove_config(config.id)


@pytest.mark.anyio
async def test_opt_in_simulator_drives_real_normalization_without_credentials(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: sent.append(kwargs))
    config = DeviceConfig.model_validate({"id": "simulator-test", "simulation_mode": True})
    with pytest.raises(ValueError):
        DeviceConfig.model_validate({"id": "simulator-test", "simulation_mode": True, "access_code": "real-secret"})
    try:
        await state.apply_config(config)
        await asyncio.sleep(0.05)
        snapshot = state.current_state(config.id)
        assert snapshot["connected"] is True
        assert snapshot["simulation_mode"] is True
        assert snapshot["print_status"] == "RUNNING"
        assert snapshot["print_progress_percent"] == 32
        assert state.request_refresh(config.id) is True
        await asyncio.sleep(0.05)
        assert sent[-1]["metrics"]["simulation_mode"] is True
    finally:
        await state.remove_config(config.id)
