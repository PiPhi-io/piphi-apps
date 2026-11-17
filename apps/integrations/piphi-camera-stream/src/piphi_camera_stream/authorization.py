from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


def authorize_runtime_request(
    request: Request, *, require_configured: bool = False
) -> None:
    expected_token = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    expected_container_id = os.getenv("PIPHI_CONTAINER_ID", "").strip()
    production = os.getenv("PIPHI_ENV", "").strip().lower() == "production"
    if not expected_token:
        if production or require_configured:
            raise HTTPException(
                status_code=503, detail="runtime authentication is not configured"
            )
        return
    provided_token = request.headers.get("X-PiPhi-Integration-Token", "").strip()
    provided_container_id = request.headers.get("X-Container-Id", "").strip()
    if not hmac.compare_digest(provided_token, expected_token) or (
        expected_container_id
        and not hmac.compare_digest(provided_container_id, expected_container_id)
    ):
        raise HTTPException(status_code=401, detail="invalid runtime credentials")
