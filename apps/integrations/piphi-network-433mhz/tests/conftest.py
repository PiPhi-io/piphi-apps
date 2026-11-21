from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PIPHI_ALLOW_UNAUTHENTICATED", "true")
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/opencode/rtl433-actions-{os.getpid()}.sqlite3",
)
os.environ.setdefault(
    "RTL433_DISCOVERY_CACHE_PATH",
    f"/tmp/opencode/rtl433-discovery-{os.getpid()}.json",
)
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
