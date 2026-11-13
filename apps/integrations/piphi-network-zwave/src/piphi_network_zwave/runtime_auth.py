from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import HTTPException, Request
from piphi_runtime_kit_python import RuntimeAuthHeaders, extract_runtime_auth_headers

from .state import runtime


def authorize_runtime_request(
    request: Request,
    *,
    allow_bootstrap: bool = False,
    payload_container_id: Any | None = None,
) -> RuntimeAuthHeaders:
    parsed = extract_runtime_auth_headers(request.headers)
    received_container_id = str(parsed.container_id or "").strip()
    received_token = str(parsed.internal_token or "").strip()
    payload_scope = str(payload_container_id or "").strip()
    expected_container_id, expected_token = runtime.auth.resolve()

    if expected_container_id or expected_token:
        if not expected_container_id or not expected_token:
            raise HTTPException(status_code=503, detail="Runtime authentication is incomplete")
        if not received_container_id or not received_token:
            raise HTTPException(status_code=401, detail="Complete runtime authentication is required")
        if not (
            secrets.compare_digest(received_container_id, expected_container_id)
            and secrets.compare_digest(received_token, expected_token)
        ):
            raise HTTPException(status_code=401, detail="Invalid runtime authentication")
        if payload_scope and not secrets.compare_digest(payload_scope, received_container_id):
            raise HTTPException(status_code=401, detail="Runtime container scope does not match payload")
        return parsed

    if allow_bootstrap and received_container_id and received_token:
        if payload_scope and not secrets.compare_digest(payload_scope, received_container_id):
            raise HTTPException(status_code=401, detail="Runtime container scope does not match payload")
        runtime.auth.update(
            container_id=received_container_id,
            internal_token=received_token,
        )
        return parsed

    if os.getenv("PIPHI_ENV", "").lower() == "production" or os.getenv("ENVIRONMENT", "").lower() == "production":
        raise HTTPException(status_code=503, detail="Runtime authentication is not configured")
    return parsed
