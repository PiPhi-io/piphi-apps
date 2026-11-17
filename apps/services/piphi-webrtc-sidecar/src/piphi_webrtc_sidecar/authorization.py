from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


def authorize_sidecar_request(request: Request) -> None:
    expected = (
        os.getenv("PIPHI_SIDECAR_TOKEN", "").strip()
        or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    )
    production = os.getenv("PIPHI_ENV", "").strip().lower() == "production"
    if not expected:
        if production:
            raise HTTPException(
                status_code=503,
                detail="camera media service authentication is not configured",
            )
        return
    scheme, _, credential = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(credential, expected):
        raise HTTPException(status_code=401, detail="camera media service authorization failed")
