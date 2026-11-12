from __future__ import annotations

import logging
import os


def _resolve_level() -> int:
    level_name = str(os.getenv("LOG_LEVEL", "INFO")).upper()
    return getattr(logging, level_name, logging.INFO)


logging.basicConfig(
    level=_resolve_level(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger("piphi_network_thinqconnect")
