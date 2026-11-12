from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-aqara-automation-actions-{os.getpid()}.sqlite3",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from piphi_network_aqara.app import app
from piphi_network_aqara.cloud.client import AqaraCloudClient
from piphi_network_aqara.cloud.models import AqaraAuthTokens, AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue
from piphi_network_aqara import runtime as runtime_module
from piphi_network_aqara.runtime import reset_runtime_state, set_cloud_client


class FakeAqaraCloudClient(AqaraCloudClient):
    def __init__(self) -> None:
        super().__init__(http_client=AsyncClient())
        self.devices: dict[str, AqaraCloudDevice] = {}
        self.resources_by_model: dict[str, list[AqaraResourceInfo]] = {}
        self.values_by_did: dict[str, list[AqaraResourceValue]] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.subscriptions: list[list[dict[str, object]]] = []
        self.unsubscriptions: list[list[dict[str, object]]] = []
        self.token_exchange_result = AqaraAuthTokens(
            access_token="access-token-1",
            refresh_token="refresh-token-1",
            open_id="open-id-1",
            expires_in=86400,
        )

    async def aclose(self) -> None:
        return None

    async def exchange_token(self, credentials, *, account, auth_code, account_type=0):
        del credentials, account, auth_code, account_type
        return self.token_exchange_result

    async def refresh_access_token(self, credentials):
        return AqaraAuthTokens(
            access_token=f"{credentials.access_token}-refreshed",
            refresh_token=credentials.refresh_token,
            open_id=credentials.open_id,
            expires_in=86400,
        )

    async def list_devices(self, credentials, *, position_id="", page_size=100):
        del credentials, position_id, page_size
        return list(self.devices.values())

    async def resource_info(self, credentials, *, model):
        del credentials
        return list(self.resources_by_model.get(model, []))

    async def resource_values(self, credentials, *, subject_id, resource_ids=None):
        del credentials, resource_ids
        return list(self.values_by_did.get(subject_id, []))

    async def write_resource(self, credentials, *, subject_id, resource_id, value):
        del credentials
        self.writes.append((subject_id, resource_id, value))

    async def subscribe_resources(self, credentials, *, resources):
        del credentials
        self.subscriptions.append(list(resources))

    async def unsubscribe_resources(self, credentials, *, resources):
        del credentials
        self.unsubscriptions.append(list(resources))


@pytest.fixture
def fake_cloud_client() -> FakeAqaraCloudClient:
    client = FakeAqaraCloudClient()
    set_cloud_client(client)
    return client


@pytest_asyncio.fixture(autouse=True)
async def _reset_runtime(fake_cloud_client: FakeAqaraCloudClient) -> AsyncIterator[None]:
    del fake_cloud_client
    await reset_runtime_state()
    yield
    await reset_runtime_state()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client


@pytest.fixture
def mock_core_runtime(mock_core):
    previous_telemetry_url = runtime_module.telemetry_client.core_base_url
    previous_event_url = runtime_module.event_client.core_base_url
    runtime_module.telemetry_client.core_base_url = mock_core.base_url
    runtime_module.event_client.core_base_url = mock_core.base_url
    try:
        yield mock_core
    finally:
        runtime_module.telemetry_client.core_base_url = previous_telemetry_url
        runtime_module.event_client.core_base_url = previous_event_url


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for background work to complete.")
