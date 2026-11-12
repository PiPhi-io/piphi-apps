from __future__ import annotations

import os


os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-zigbee-automation-actions-{os.getpid()}.sqlite3",
)
