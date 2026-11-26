from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-zigbee-automation-actions-{os.getpid()}.sqlite3",
)
os.environ.setdefault(
    "PIPHI_ZIGBEE_STATE_PATH",
    f"/tmp/piphi-zigbee-configs-{uuid4().hex}.json",
)
