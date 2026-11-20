from __future__ import annotations

import os

import pytest

os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-spi-automation-actions-{os.getpid()}.sqlite3",
)


@pytest.fixture(autouse=True)
def allow_unauthenticated_test_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
