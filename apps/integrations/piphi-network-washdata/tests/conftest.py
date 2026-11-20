import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
os.environ.setdefault(
    "PIPHI_WASHDATA_STATE_PATH", f"/tmp/opencode/washdata-state-tests-{os.getpid()}.sqlite3"
)
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH", f"/tmp/opencode/washdata-actions-tests-{os.getpid()}.sqlite3"
)
os.environ.setdefault("PIPHI_ALLOW_UNAUTHENTICATED", "true")
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
