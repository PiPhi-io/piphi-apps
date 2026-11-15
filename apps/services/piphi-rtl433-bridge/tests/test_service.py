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
