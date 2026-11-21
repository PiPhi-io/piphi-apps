from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("PIPHI_ALLOW_UNAUTHENTICATED", "true")
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
