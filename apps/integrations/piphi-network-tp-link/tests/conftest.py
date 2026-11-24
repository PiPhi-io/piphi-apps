from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-tp-link-automation-actions-{os.getpid()}.sqlite3",
)
os.environ.setdefault("PIPHI_INTEGRATION_INTERNAL_TOKEN", "secret-token")

from fastapi.testclient import TestClient as _TestClient

_original_init = _TestClient.__init__


def _authenticated_test_client_init(self, *args, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("X-PiPhi-Integration-Token", "secret-token")
    _original_init(self, *args, headers=headers, **kwargs)


_TestClient.__init__ = _authenticated_test_client_init

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
