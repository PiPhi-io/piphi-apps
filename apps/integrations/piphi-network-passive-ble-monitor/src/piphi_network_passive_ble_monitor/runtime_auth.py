from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request
from piphi_runtime_kit_python import extract_runtime_auth_headers

from .state import runtime


def authorize_runtime_request(request: Request) -> None:
    parsed = extract_runtime_auth_headers(request.headers)
    supplied_container = str(parsed.container_id or "").strip()
    supplied_token = str(parsed.internal_token or "").strip()
    expected_container, runtime_token = runtime.auth.resolve()
    configured_token = os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "").strip()
    expected_token = configured_token or runtime_token
    if configured_token:
        expected_container = ""
    if not expected_token:
        if request.url.path in {"/config", "/config/sync"} and supplied_container and supplied_token:
            runtime.auth.update(container_id=supplied_container, internal_token=supplied_token)
            return
        raise HTTPException(status_code=503, detail="runtime authentication is not configured")
    if not supplied_token or not secrets.compare_digest(supplied_token, expected_token):
        raise HTTPException(status_code=401, detail="invalid runtime authentication")
    if expected_container and (
        not supplied_container or not secrets.compare_digest(supplied_container, expected_container)
    ):
        raise HTTPException(status_code=401, detail="invalid runtime container scope")
