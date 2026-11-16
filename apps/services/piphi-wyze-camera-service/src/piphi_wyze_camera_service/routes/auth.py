from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_wyze_bridge_authorization(
    authorization: str | None = Header(default=None),
) -> None:
    expected = (
        os.getenv("PIPHI_SIDECAR_TOKEN", "").strip()
        or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    )
    production = os.getenv("PIPHI_ENV", "development").strip().lower() == "production"
    if not expected:
        if production:
            raise HTTPException(
                status_code=503,
                detail="Wyze bridge authentication is not configured",
            )
        return

    scheme, _, credential = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(credential, expected):
        raise HTTPException(status_code=401, detail="Wyze bridge authorization failed")
