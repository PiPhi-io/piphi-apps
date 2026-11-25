from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import Request as FastAPIRequest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)

from ..network_policy import require_local_endpoint
from ..parent_contract_v1 import (
    MAX_PAYLOAD_BYTES,
    CompletedResponse,
    ContractPayloadError,
    ErrorCode,
    ErrorResponse,
    parse_request,
)
from ..state import get_controller, get_controller_by_target
from ..transport import (
    AdbCommandTimeoutError,
    AdbOfflineError,
    AdbOutcomeUnknownError,
    AdbQueueFullError,
    AdbTransportError,
    AdbUnauthorizedError,
    CommandRunner,
    SubprocessAdbRunner,
)

router = APIRouter(prefix="/v1/adb", tags=["parent-sidecar"])
pairing_runner: CommandRunner = SubprocessAdbRunner()


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    pairing_code: SecretStr
    timeout_ms: int = Field(default=30_000, ge=1_000, le=30_000)

    @field_validator("pairing_code")
    @classmethod
    def validate_pairing_code(cls, value: SecretStr) -> SecretStr:
        code = value.get_secret_value()
        if len(code) != 6 or not code.isdecimal():
            raise ValueError("pairing code must be exactly six digits")
        return value


_ADB_MDNS_SERVICES = frozenset(
    {"_adb-tls-pairing._tcp", "_adb-tls-connect._tcp"}
)


@router.get("/mdns")
async def mdns_services() -> dict[str, list[dict[str, object]]]:
    result = await pairing_runner.run(("mdns", "services"), timeout_ms=3_000)
    if result.returncode != 0 or result.output_truncated:
        raise HTTPException(status_code=503, detail="ADB mDNS discovery is unavailable")
    candidates: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[-2].rstrip(".") not in _ADB_MDNS_SERVICES:
            continue
        endpoint = parts[-1]
        host, separator, raw_port = endpoint.rpartition(":")
        if not separator or not raw_port.isdecimal():
            continue
        port = int(raw_port)
        if not host or not 1 <= port <= 65535:
            continue
        try:
            await require_local_endpoint(host, port)
        except ValueError:
            continue
        candidates.append(
            {
                "service_type": parts[-2].rstrip("."),
                "host": host,
                "port": port,
                "verification_status": "unverified",
            }
        )
    return {"candidates": candidates[:32]}


@router.post("/pair")
async def pair(payload: PairRequest) -> dict[str, str]:
    await require_local_endpoint(payload.host, payload.port)
    endpoint = f"{payload.host}:{payload.port}"
    result = await pairing_runner.run(
        ("pair", endpoint, payload.pairing_code.get_secret_value()),
        timeout_ms=payload.timeout_ms,
    )
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if result.returncode != 0 or "successfully paired" not in combined:
        raise HTTPException(status_code=401, detail="ADB pairing was rejected")
    return {"status": "paired"}


@router.get("/snapshot")
async def snapshot(
    config_id: Annotated[
        str | None,
        Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
) -> dict[str, Any]:
    return get_controller(config_id).snapshot()


@router.post("/reconnect")
async def reconnect(
    request: FastAPIRequest,
    config_id: Annotated[
        str | None,
        Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"),
    ] = None,
) -> dict[str, Any]:
    if request.headers.get("content-length", "0") != "0" or request.headers.get(
        "transfer-encoding"
    ):
        raise HTTPException(status_code=400, detail="Reconnect does not accept a request body")
    controller = get_controller(config_id)
    try:
        await controller.reconnect()
    except AdbQueueFullError as exc:
        raise HTTPException(status_code=429, detail="Target command queue is full") from exc
    return controller.snapshot()


@router.post("/execute")
async def execute(http_request: FastAPIRequest) -> dict[str, Any]:
    payload = bytearray()
    async for chunk in http_request.stream():
        payload.extend(chunk)
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Contract payload exceeds byte limit")
    try:
        request = parse_request(bytes(payload))
    except (ContractPayloadError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid parent contract payload") from exc

    controller = get_controller_by_target(request.target.target_id)
    if controller is None:
        return ErrorResponse(
            version="1",
            request_id=request.request_id,
            status="error",
            error=ErrorCode.UNSUPPORTED,
            message="unknown or expired target lease",
        ).model_dump(mode="json")
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            result = await controller.execute(request)
    except AdbUnauthorizedError:
        return _error(request.request_id, ErrorCode.UNAUTHORIZED, "target authorization required")
    except AdbQueueFullError:
        return _error(
            request.request_id,
            ErrorCode.QUEUE_FULL,
            "target command queue is full",
            retry_after_ms=250,
        )
    except AdbCommandTimeoutError:
        return _error(request.request_id, ErrorCode.TIMEOUT, "target command timed out")
    except TimeoutError:
        controller.record_request_timeout()
        return _error(request.request_id, ErrorCode.TIMEOUT, "target request timed out")
    except AdbOutcomeUnknownError:
        return _error(
            request.request_id,
            ErrorCode.OFFLINE,
            "target disconnected; key event outcome is unknown",
        )
    except AdbOfflineError:
        return _error(request.request_id, ErrorCode.OFFLINE, "target is offline")
    except (AdbTransportError, OSError):
        return _error(request.request_id, ErrorCode.OFFLINE, "target transport failed")
    except ValueError:
        return _error(request.request_id, ErrorCode.UNSUPPORTED, "request is not supported")
    return CompletedResponse.model_validate(
        {
            "version": "1",
            "request_id": request.request_id,
            "status": "completed",
            "result": result,
        }
    ).model_dump(mode="json")


def _error(
    request_id: str,
    code: ErrorCode,
    message: str,
    *,
    retry_after_ms: int | None = None,
) -> dict[str, Any]:
    return ErrorResponse(
        version="1",
        request_id=request_id,
        status="error",
        error=code,
        message=message,
        retry_after_ms=retry_after_ms,
    ).model_dump(mode="json")
