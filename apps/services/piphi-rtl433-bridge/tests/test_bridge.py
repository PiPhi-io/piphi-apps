import asyncio
import json

import httpx
import pytest

from piphi_rtl433_bridge.bridge import Rtl433Bridge, parse_packet_line
from piphi_rtl433_bridge.config import build_bridge_config


class DummyResponse:
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise

    def raise_for_status(self) -> None:
        if self.should_raise:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("POST", "http://runtime.test/ingest/rtl433"),
                response=httpx.Response(500),
            )


class DummyHttpClient:
    def __init__(self, responses: list[DummyResponse] | None = None) -> None:
        self.responses = responses or [DummyResponse()]
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


class DummyMqttClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def publish(self, topic: str, *, payload: str, qos: int) -> None:
        self.calls.append({"topic": topic, "payload": payload, "qos": qos})


class DummyStream:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = list(lines)

    async def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        return b""


class DummyProcess:
    def __init__(
        self,
        *,
        stdout_lines: list[bytes] | None = None,
        stderr_lines: list[bytes] | None = None,
        returncode: int | None = 0,
    ) -> None:
        self.stdout = DummyStream(stdout_lines or [])
        self.stderr = DummyStream(stderr_lines or [])
        self.returncode = returncode
        self.kill_called = False
        self.wait_called = False

    def kill(self) -> None:
        self.kill_called = True
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_called = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def make_config(**overrides):
    defaults = {
        "http_forward_enabled": True,
        "runtime_ingest_url": "http://runtime.test/ingest/rtl433",
        "rtl433_command_text": "rtl_433 -F json",
        "forward_timeout_seconds": 10.0,
        "retry_delay_seconds": 0.01,
        "startup_delay_seconds": 0.0,
        "extra_headers_json": '{"X-Test":"1"}',
        "mqtt_enabled": False,
        "mqtt_hostname": "mqtt.test",
        "mqtt_port": 1883,
        "mqtt_username": None,
        "mqtt_password": None,
        "mqtt_client_id": None,
        "mqtt_qos": 1,
        "mqtt_topic_root": "piphi/sources/rtl433/",
    }
    defaults.update(overrides)
    return build_bridge_config(**defaults)


def test_parse_packet_line_accepts_json_object() -> None:
    packet = parse_packet_line(b'{"model":"Nexus-TH","id":42,"temperature_C":21.5}\n')

    assert packet is not None
    assert packet["model"] == "Nexus-TH"
    assert packet["id"] == 42


def test_parse_packet_line_rejects_non_json() -> None:
    assert parse_packet_line("not-json") is None


def test_parse_packet_line_rejects_json_arrays() -> None:
    assert parse_packet_line('[{"model":"Nexus-TH"}]') is None


def test_parse_packet_line_rejects_blank_lines() -> None:
    assert parse_packet_line(b"\n") is None


def test_forward_packet_http_posts_payload_and_headers() -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)
    client = DummyHttpClient()

    asyncio.run(bridge._forward_packet_http(client, {"model": "Nexus-TH"}))

    assert client.calls == [
        {
            "url": "http://runtime.test/ingest/rtl433",
            "json": {"model": "Nexus-TH"},
            "headers": {"X-Test": "1"},
        }
    ]


def test_forward_packet_http_requires_client_when_enabled() -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)

    try:
        asyncio.run(bridge._forward_packet_http(None, {"model": "Nexus-TH"}))
    except RuntimeError as exc:
        assert "no HTTP client" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when HTTP client is missing")


def test_forward_packet_http_noops_when_disabled() -> None:
    config = make_config(http_forward_enabled=False)
    bridge = Rtl433Bridge(config)

    asyncio.run(bridge._forward_packet_http(None, {"model": "Nexus-TH"}))


def test_forward_packet_mqtt_publishes_base_and_model_topics() -> None:
    config = make_config(mqtt_enabled=True)
    bridge = Rtl433Bridge(config)
    client = DummyMqttClient()

    asyncio.run(bridge._forward_packet_mqtt(client, {"model": "Nexus TH", "id": 42}))

    assert [call["topic"] for call in client.calls] == [
        "piphi/sources/rtl433/packets",
        "piphi/sources/rtl433/models/Nexus_TH/packets",
    ]
    first_payload = json.loads(client.calls[0]["payload"])
    assert first_payload["packet"]["id"] == 42


def test_forward_packet_mqtt_skips_model_topic_when_model_missing() -> None:
    config = make_config(mqtt_enabled=True)
    bridge = Rtl433Bridge(config)
    client = DummyMqttClient()

    asyncio.run(bridge._forward_packet_mqtt(client, {"id": 42}))

    assert [call["topic"] for call in client.calls] == ["piphi/sources/rtl433/packets"]


def test_forward_packet_mqtt_requires_client_when_enabled() -> None:
    config = make_config(mqtt_enabled=True)
    bridge = Rtl433Bridge(config)

    with pytest.raises(RuntimeError, match="no MQTT client"):
        asyncio.run(bridge._forward_packet_mqtt(None, {"model": "Nexus-TH"}))


def test_forward_packet_mqtt_noops_when_disabled() -> None:
    config = make_config(mqtt_enabled=False)
    bridge = Rtl433Bridge(config)

    asyncio.run(bridge._forward_packet_mqtt(None, {"model": "Nexus-TH"}))


def test_forward_packet_retries_then_succeeds(monkeypatch) -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)
    client = DummyHttpClient([DummyResponse(should_raise=True), DummyResponse()])
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("piphi_rtl433_bridge.bridge.asyncio.sleep", fake_sleep)

    asyncio.run(bridge.forward_packet(client, None, {"model": "Nexus-TH"}))

    assert len(client.calls) == 2
    assert sleep_calls == [0.01]
    assert bridge.forwarded_count == 1


def test_forward_packet_uses_both_http_and_mqtt_when_enabled() -> None:
    config = make_config(mqtt_enabled=True)
    bridge = Rtl433Bridge(config)
    http_client = DummyHttpClient()
    mqtt_client = DummyMqttClient()

    asyncio.run(
        bridge.forward_packet(
            http_client,
            mqtt_client,
            {"model": "Nexus TH", "id": 42},
        )
    )

    assert len(http_client.calls) == 1
    assert len(mqtt_client.calls) == 2
    assert bridge.forwarded_count == 1


def test_forward_stdout_counts_invalid_lines_and_forwards_valid_packets(monkeypatch) -> None:
    config = make_config(http_forward_enabled=False, mqtt_enabled=False)
    bridge = Rtl433Bridge(config)
    process = DummyProcess(
        stdout_lines=[
            b"not-json\n",
            b'{"model":"Nexus-TH","id":42}\n',
            b"\n",
        ]
    )
    forwarded_packets: list[dict[str, object]] = []

    async def fake_sleep(_delay: float) -> None:
        return None

    async def fake_forward_packet(_http_client, _mqtt_client, packet: dict[str, object]) -> None:
        forwarded_packets.append(packet)

    monkeypatch.setattr("piphi_rtl433_bridge.bridge.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(bridge, "forward_packet", fake_forward_packet)

    asyncio.run(bridge._forward_stdout(process))

    assert bridge.invalid_line_count == 2
    assert forwarded_packets == [{"model": "Nexus-TH", "id": 42}]


def test_log_stderr_emits_only_non_blank_messages(caplog) -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)
    process = DummyProcess(
        stderr_lines=[
            b"first line\n",
            b"\n",
            b"second line\n",
        ]
    )

    with caplog.at_level("INFO", logger="piphi_rtl433_bridge"):
        asyncio.run(bridge._log_stderr(process))

    messages = [record.message for record in caplog.records]
    assert "rtl433 stderr=first line" in messages
    assert "rtl433 stderr=second line" in messages
    assert len(messages) == 2


def test_run_once_kills_process_when_still_running(monkeypatch) -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)
    process = DummyProcess(returncode=None)

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return process

    async def fake_forward_stdout(_process) -> None:
        return None

    async def fake_log_stderr(_process) -> None:
        return None

    monkeypatch.setattr(
        "piphi_rtl433_bridge.bridge.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(bridge, "_forward_stdout", fake_forward_stdout)
    monkeypatch.setattr(bridge, "_log_stderr", fake_log_stderr)

    asyncio.run(bridge.run_once())

    assert process.kill_called is True
    assert process.wait_called is True


def test_run_once_does_not_kill_process_when_already_exited(monkeypatch) -> None:
    config = make_config()
    bridge = Rtl433Bridge(config)
    process = DummyProcess(returncode=0)

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return process

    async def fake_forward_stdout(_process) -> None:
        return None

    async def fake_log_stderr(_process) -> None:
        return None

    monkeypatch.setattr(
        "piphi_rtl433_bridge.bridge.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(bridge, "_forward_stdout", fake_forward_stdout)
    monkeypatch.setattr(bridge, "_log_stderr", fake_log_stderr)

    asyncio.run(bridge.run_once())

    assert process.kill_called is False
    assert process.wait_called is False


def test_run_forever_logs_exception_and_sleeps(monkeypatch, caplog) -> None:
    config = make_config(retry_delay_seconds=0.25)
    bridge = Rtl433Bridge(config)
    sleep_calls: list[float] = []
    run_once_calls = {"count": 0}

    async def fake_run_once() -> None:
        run_once_calls["count"] += 1
        if run_once_calls["count"] == 1:
            raise RuntimeError("boom")
        raise asyncio.CancelledError()

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(bridge, "run_once", fake_run_once)
    monkeypatch.setattr("piphi_rtl433_bridge.bridge.asyncio.sleep", fake_sleep)

    with caplog.at_level("ERROR", logger="piphi_rtl433_bridge"):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(bridge.run_forever())

    assert run_once_calls["count"] == 2
    assert sleep_calls == [0.25]
    assert any("bridge_cycle_failed error=boom" in record.message for record in caplog.records)
