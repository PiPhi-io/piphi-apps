from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, Request
from piphi_runtime_kit_python import RuntimeAuthHeaders, extract_runtime_auth_headers


def authorize_runtime_request(
    request: Request,
    *,
    runtime_context: Any,
    allow_bootstrap: bool = False,
) -> RuntimeAuthHeaders:
    parsed = extract_runtime_auth_headers(request.headers)
    container_id = str(parsed.container_id or "").strip()
    token = str(parsed.internal_token or "").strip()
    if not container_id or not token:
        raise HTTPException(status_code=401, detail="Complete runtime authentication is required")
    expected_container_id, expected_token = runtime_context.auth.resolve()
    if expected_container_id or expected_token:
        if not expected_container_id or not expected_token:
            raise HTTPException(status_code=503, detail="Runtime authentication is incomplete")
        if not (
            secrets.compare_digest(container_id, expected_container_id)
            and secrets.compare_digest(token, expected_token)
        ):
            raise HTTPException(status_code=401, detail="Invalid runtime authentication")
        return parsed
    if not allow_bootstrap:
        raise HTTPException(status_code=503, detail="Runtime authentication is not configured")
    runtime_context.auth.update(container_id=container_id, internal_token=token)
    return parsed
