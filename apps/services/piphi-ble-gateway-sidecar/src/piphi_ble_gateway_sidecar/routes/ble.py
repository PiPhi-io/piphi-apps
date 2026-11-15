from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from ..ble_models import Matcher
from ..gateway import MAX_REPLAY_LIMIT, gateway

router = APIRouter(prefix="/v1/ble", tags=["ble"])
CONSUMER_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


class MatcherRequest(BaseModel):
    device_handles: list[str] = Field(default_factory=list, max_length=128)
    manufacturer_ids: list[int] = Field(default_factory=list, max_length=64)
    service_uuids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("manufacturer_ids")
    @classmethod
    def valid_manufacturer_ids(cls, value: list[int]) -> list[int]:
        if any(item < 0 or item > 65535 for item in value):
            raise ValueError("manufacturer IDs must be between 0 and 65535")
        return value

    @field_validator("service_uuids")
    @classmethod
    def valid_service_uuids(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 64 for item in value):
            raise ValueError("service UUID matchers must contain 1 to 64 characters")
        return value

    @field_validator("device_handles")
    @classmethod
    def valid_device_handles(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"ble_[0-9a-f]{32}", item) for item in value):
            raise ValueError("device handle matchers must use the opaque ble_ format")
        return value


class ConsumerRequest(BaseModel):
    schema_version: Literal["piphi.ble.consumer.v1"] = "piphi.ble.consumer.v1"
    matcher: MatcherRequest
    scan_mode: Literal["auto", "active", "passive"] = "auto"
    queue_capacity: int = Field(default=128, ge=1, le=1024)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer authorization required")
    return authorization[7:]


def _consumer_id(value: str) -> str:
    if not CONSUMER_ID.fullmatch(value):
        raise HTTPException(status_code=422, detail="invalid consumer_id")
    return value


def _consumer(consumer_id: str, authorization: str | None):
    try:
        return gateway.authorize(_consumer_id(consumer_id), _bearer(authorization))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/consumers/{consumer_id}")
async def put_consumer(consumer_id: str, request: ConsumerRequest, authorization: str | None = Header(None)):
    consumer_id = _consumer_id(consumer_id)
    token = _bearer(authorization)
    if not 16 <= len(token) <= 256:
        raise HTTPException(status_code=401, detail="consumer bearer token must contain 16 to 256 characters")
    matcher = Matcher(
        frozenset(request.matcher.device_handles),
        frozenset(request.matcher.manufacturer_ids),
        frozenset(item.lower() for item in request.matcher.service_uuids),
    )
    try:
        consumer = await gateway.register(
            consumer_id, token, matcher, request.scan_mode, request.queue_capacity
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"consumer_id": consumer.consumer_id, "scan_mode": consumer.mode,
            "queue_capacity": consumer.capacity, "effective_scan_mode": gateway.plan()}


@router.delete("/consumers/{consumer_id}", status_code=204)
async def delete_consumer(consumer_id: str, authorization: str | None = Header(None)):
    token = _bearer(authorization)
    try:
        await gateway.unregister(_consumer_id(consumer_id), token)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/observations/{consumer_id}")
async def observations(
    consumer_id: str,
    after: int = Query(default=0, ge=0, le=9_223_372_036_854_775_807),
    limit: int = Query(default=100, ge=1, le=MAX_REPLAY_LIMIT),
    authorization: str | None = Header(None),
):
    consumer = _consumer(consumer_id, authorization)
    items = gateway.observations(consumer, after, limit)
    cursor = items[-1]["sequence"] if items else after
    return {"consumer_id": consumer_id, "observations": items,
            "cursor": cursor, "gap": gateway.cursor_gap(consumer, after),
            "receiver_healthy": gateway.receiver_healthy}


@router.get("/snapshot/{consumer_id}")
async def snapshot(consumer_id: str, authorization: str | None = Header(None)):
    consumer = _consumer(consumer_id, authorization)
    return {
        "consumer_id": consumer_id,
        "observations": gateway.snapshot(consumer),
        "cursor": gateway.sequence,
        "gap": False,
        "receiver_healthy": gateway.receiver_healthy,
        "topology_revision": 1,
        "receivers": [{
            "receiver_id": gateway.receiver_id,
            "receiver_kind": gateway.scanner.receiver_kind,
            "healthy": gateway.receiver_healthy,
        }],
    }
