from __future__ import annotations

import pytest

from piphi_network_android_tv.state import runtime


@pytest.fixture(autouse=True)
def configured_runtime_auth() -> None:
    runtime.auth.update(container_id="test-container", internal_token="test-token")
