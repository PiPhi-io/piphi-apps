from __future__ import annotations

from fastapi import Request

from ..authorization import authorize_service_request


def require_wyze_bridge_authorization(request: Request) -> None:
    authorize_service_request(request)
