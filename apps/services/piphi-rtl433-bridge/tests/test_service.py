import asyncio

import pytest
from fastapi import HTTPException

from piphi_rtl433_bridge.config import load_bridge_config
from piphi_rtl433_bridge.service import (
    BridgeSupervisor,
    RadioConfigurationRequest,
    _authorize_service_request,
)


def test_supervisor_restarts_bridge_with_discovery_settings() -> None:
    created = []
    cancelled = []

    class FakeBridge:
        def __init__(self, config):
            created.append(config)

        async def run_forever(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    async def run() -> None:
        supervisor = BridgeSupervisor(load_bridge_config(), bridge_factory=FakeBridge)
        await supervisor.start()
        await asyncio.sleep(0)
        updated = await supervisor.configure(
            RadioConfigurationRequest(frequency="868mhz", rtlsdr_device="serial=radio-2")
        )
        await asyncio.sleep(0)
        assert updated.frequency == "868M"
        assert updated.rtl_sdr_device == "serial=radio-2"
        assert len(created) == 2
        assert cancelled == [True]
        await supervisor.stop()

    asyncio.run(run())


def test_radio_reconfiguration_authentication_is_constant_time_boundary(monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_SERVICE_AUTH_TOKEN", "service-secret")
    with pytest.raises(HTTPException) as missing:
        _authorize_service_request(None)
    with pytest.raises(HTTPException) as invalid:
        _authorize_service_request("wrong")
    assert missing.value.status_code == 401
    assert invalid.value.status_code == 401
    assert _authorize_service_request("service-secret") is None


def test_radio_reconfiguration_authentication_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_SERVICE_AUTH_TOKEN", raising=False)
    with pytest.raises(HTTPException) as missing:
        _authorize_service_request(None)
    assert missing.value.status_code == 503


def test_supervisor_rolls_back_failed_reconfiguration(tmp_path) -> None:
    created = []

    class FakeBridge:
        def __init__(self, config):
            self.config = config
            created.append(config.frequency)
            self.forwarded_count = 0
            self.invalid_line_count = 0
            self.dropped_count = 0
            self.duplicate_count = 0
            self.retry_count = 0
            self.failed_count = 0

        async def run_forever(self):
            if self.config.frequency == "868M":
                raise RuntimeError("receiver unavailable")
            await asyncio.Event().wait()

    async def run() -> None:
        state_path = tmp_path / "radio.json"
        supervisor = BridgeSupervisor(
            load_bridge_config(), bridge_factory=FakeBridge, state_path=state_path
        )
        await supervisor.start()
        with pytest.raises(ValueError, match="could not be started"):
            await supervisor.configure(RadioConfigurationRequest(frequency="868mhz"))
        assert supervisor.config.frequency == "433.92M"
        assert supervisor.health()["process_supervisor_running"] is True
        assert not state_path.exists()
        assert created == ["433.92M", "868M", "433.92M"]
        await supervisor.stop()

    asyncio.run(run())


def test_supervisor_persists_successful_reconfiguration(tmp_path) -> None:
    class FakeBridge:
        def __init__(self, _config):
            pass

        async def run_forever(self):
            await asyncio.Event().wait()

    async def run() -> None:
        state_path = tmp_path / "radio.json"
        supervisor = BridgeSupervisor(
            load_bridge_config(), bridge_factory=FakeBridge, state_path=state_path
        )
        await supervisor.start()
        await supervisor.configure(
            RadioConfigurationRequest(frequency="915mhz", rtlsdr_device="serial=receiver-1")
        )
        payload = __import__("json").loads(state_path.read_text())
        assert payload["frequency"] == "915M"
        assert payload["rtlsdr_device"] == "serial=receiver-1"
        assert "runtime_ingest_url" not in payload
        await supervisor.stop()

    asyncio.run(run())
