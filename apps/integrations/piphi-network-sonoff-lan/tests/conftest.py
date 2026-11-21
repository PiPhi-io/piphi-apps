import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
os.environ.setdefault("PIPHI_ALLOW_UNAUTHENTICATED", "true")
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/opencode/sonoff-lan-actions-{os.getpid()}.sqlite3",
)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
