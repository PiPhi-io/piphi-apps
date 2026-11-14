from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


def authorize_sidecar_request(request: Request) -> None:
    expected = str(
        os.getenv("PIPHI_MODBUS_SIDECAR_TOKEN")
        or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
        or ""
    ).strip()
    if not expected:
        if os.getenv("PIPHI_ENV", "").lower() == "production" or os.getenv(
            "ENVIRONMENT", ""
        ).lower() == "production":
            raise HTTPException(status_code=503, detail="Sidecar authentication is not configured")
        return
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(credential, expected):
        raise HTTPException(status_code=401, detail="Invalid sidecar authentication")
