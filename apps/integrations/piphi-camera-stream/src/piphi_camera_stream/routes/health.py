from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])
_DIAGNOSTIC_HASH_KEY = secrets.token_bytes(32)


def _config_fingerprint(config_id: str) -> str:
    return hashlib.blake2s(
        config_id.encode("utf-8"), key=_DIAGNOSTIC_HASH_KEY, digest_size=8
    ).hexdigest()


@router.get("/health")
async def health():
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "active_config_fingerprints": [
                _config_fingerprint(config_id) for config_id in registry.ids()
            ],
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
