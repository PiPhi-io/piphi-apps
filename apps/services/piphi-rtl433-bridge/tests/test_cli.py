from click.testing import CliRunner
import httpx
import pytest

from click import BadParameter

from piphi_rtl433_bridge.cli import (
    _config_to_dict,
    _parse_header_pairs,
    _ping_runtime,
    _validate_extra_headers_json,
    main,
)
from piphi_rtl433_bridge.config import build_bridge_config


def test_print_config_supports_repeatable_header_option() -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "print-config",
            "--runtime-ingest-url",
            "http://runtime.test/ingest/rtl433",
            "--header",
            "X-One=1",
            "--header",
            "X-Two=2",
        ],
    )

    assert result.exit_code == 0
    assert '"X-One": "1"' in result.output
    assert '"X-Two": "2"' in result.output


def test_run_dry_run_prints_resolved_config() -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "run",
            "--dry-run",
            "--rtl433-command",
            "rtl_433 -F json -M time:unix",
        ],
    )

    assert result.exit_code == 0
    assert '"rtl433_command": [' in result.output


def test_print_config_shows_friendly_radio_preset_command() -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "print-config",
            "--radio-band",
            "915mhz",
            "--rtl-sdr-device",
            "1",
            "--receiver-gain",
            "32.8",
            "--rtl433-protocols",
            "40,41",
        ],
    )

    assert result.exit_code == 0
    assert '"radio_band": "915mhz"' in result.output
    assert '"frequency": "915M"' in result.output
    assert '"-R"' in result.output


def test_invalid_header_pair_returns_error() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["print-config", "--header", "missing-separator"])

    assert result.exit_code != 0
    assert "KEY=VALUE" in result.output


def test_empty_header_key_returns_error() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["print-config", "--header", "=value"])

    assert result.exit_code != 0
    assert "missing a key" in result.output


def test_invalid_extra_headers_json_returns_error() -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["print-config", "--extra-headers-json", "{bad-json"],
    )

    assert result.exit_code != 0
    assert "Invalid JSON" in result.output


def test_ping_runtime_success_returns_zero_exit(monkeypatch) -> None:
    runner = CliRunner()

    async def fake_ping_runtime(_config):
        return {
            "reachable": True,
            "status_code": 200,
            "runtime_ingest_url": "http://runtime.test/ingest/rtl433",
        }

    monkeypatch.setattr("piphi_rtl433_bridge.cli._ping_runtime", fake_ping_runtime)

    result = runner.invoke(main, ["ping-runtime"])

    assert result.exit_code == 0
    assert '"reachable": true' in result.output


def test_ping_runtime_failure_returns_non_zero_exit(monkeypatch) -> None:
    runner = CliRunner()

    async def fake_ping_runtime(_config):
        return {
            "reachable": False,
            "error": "connection refused",
            "runtime_ingest_url": "http://runtime.test/ingest/rtl433",
        }

    monkeypatch.setattr("piphi_rtl433_bridge.cli._ping_runtime", fake_ping_runtime)

    result = runner.invoke(main, ["ping-runtime"])

    assert result.exit_code == 1
    assert '"reachable": false' in result.output


def test_ping_runtime_disabled_returns_non_zero_exit() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["ping-runtime", "--no-http-forward-enabled"])

    assert result.exit_code == 1
    assert "HTTP forwarding is disabled" in result.output


def test_parse_header_pairs_allows_equals_in_value() -> None:
    assert _parse_header_pairs(("Authorization=Bearer=token",)) == {
        "Authorization": "Bearer=token"
    }


def test_validate_extra_headers_json_rejects_non_object() -> None:
    with pytest.raises(BadParameter, match="must be a JSON object"):
        _validate_extra_headers_json('["bad"]')


def test_config_to_dict_omits_sensitive_mqtt_password() -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.test/ingest/rtl433",
        rtl433_command_text="rtl_433 -F json",
        forward_timeout_seconds=1.0,
        retry_delay_seconds=1.0,
        startup_delay_seconds=0.0,
        mqtt_enabled=True,
        mqtt_password="secret",
        mqtt_client_id="bridge-1",
    )

    payload = _config_to_dict(config)

    assert payload["mqtt_client_id"] == "bridge-1"
    assert "mqtt_password" not in payload


@pytest.mark.anyio
async def test_ping_runtime_returns_failure_on_transport_error(monkeypatch) -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.test/ingest/rtl433",
        rtl433_command_text="rtl_433 -F json",
        forward_timeout_seconds=1.0,
        retry_delay_seconds=1.0,
        startup_delay_seconds=0.0,
    )

    class FailingAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            raise httpx.ConnectError("refused", request=httpx.Request("GET", url))

    monkeypatch.setattr("piphi_rtl433_bridge.cli.httpx.AsyncClient", lambda timeout: FailingAsyncClient())

    result = await _ping_runtime(config)

    assert result["reachable"] is False
    assert "refused" in result["error"]


@pytest.mark.anyio
async def test_ping_runtime_success_passes_headers(monkeypatch) -> None:
    config = build_bridge_config(
        http_forward_enabled=True,
        runtime_ingest_url="http://runtime.test/ingest/rtl433",
        rtl433_command_text="rtl_433 -F json",
        forward_timeout_seconds=1.0,
        retry_delay_seconds=1.0,
        startup_delay_seconds=0.0,
        extra_headers={"X-Test": "1"},
    )
    captured: dict[str, object] = {}

    class SuccessAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return type("Response", (), {"status_code": 204})()

    monkeypatch.setattr("piphi_rtl433_bridge.cli.httpx.AsyncClient", lambda timeout: SuccessAsyncClient())

    result = await _ping_runtime(config)

    assert result["reachable"] is True
    assert captured == {
        "url": "http://runtime.test/ingest/rtl433",
        "headers": {"X-Test": "1"},
    }
