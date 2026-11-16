"""Version 1 of the bounded parent-to-ADB-sidecar message contract.

This module validates the private parent contract. Transport command construction
remains isolated in ``transport.py``.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

CONTRACT_VERSION = "1"
MAX_PAYLOAD_BYTES = 4_096
MAX_PROPERTY_COUNT = 8

RequestId = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$"),
]
OpaqueTargetId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ErrorMessage = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


class ContractModel(BaseModel):
    """Strict base model that rejects fields outside the versioned contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Target(ContractModel):
    """Exactly one explicit ADB target selector."""

    # The parent uses a lease/transport identifier resolved by the sidecar,
    # never a raw ADB serial, host, or "first device" fallback.
    target_id: OpaqueTargetId


class KeyCode(StrEnum):
    BACK = "back"
    HOME = "home"
    ENTER = "enter"
    DPAD_UP = "dpad_up"
    DPAD_DOWN = "dpad_down"
    DPAD_LEFT = "dpad_left"
    DPAD_RIGHT = "dpad_right"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    VOLUME_MUTE = "volume_mute"
    MEDIA_PLAY_PAUSE = "media_play_pause"


class ReadableProperty(StrEnum):
    PRODUCT_MANUFACTURER = "ro.product.manufacturer"
    PRODUCT_MODEL = "ro.product.model"
    ANDROID_RELEASE = "ro.build.version.release"
    ANDROID_SDK = "ro.build.version.sdk"


class KeyEvent(ContractModel):
    operation: Literal["key_event"]
    key: KeyCode
    repeat: int = Field(default=1, strict=True, ge=1, le=10)


class PropertyQuery(ContractModel):
    operation: Literal["property_query"]
    properties: list[ReadableProperty] = Field(
        min_length=1,
        max_length=MAX_PROPERTY_COUNT,
    )

    @field_validator("properties")
    @classmethod
    def properties_must_be_unique(
        cls, properties: list[ReadableProperty]
    ) -> list[ReadableProperty]:
        if len(properties) != len(set(properties)):
            raise ValueError("properties must be unique")
        return properties


Operation = Annotated[KeyEvent | PropertyQuery, Field(discriminator="operation")]


class Request(ContractModel):
    version: Literal["1"]
    request_id: RequestId
    target: Target
    timeout_ms: int = Field(strict=True, ge=100, le=30_000)
    command: Operation


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    TIMEOUT = "timeout"
    QUEUE_FULL = "queue_full"
    UNSUPPORTED = "unsupported"


class AcceptedResponse(ContractModel):
    version: Literal["1"]
    request_id: RequestId
    status: Literal["accepted"]


class KeyEventResult(ContractModel):
    operation: Literal["key_event"]
    repeats_completed: int = Field(strict=True, ge=1, le=10)


class PropertyQueryResult(ContractModel):
    operation: Literal["property_query"]
    properties: dict[ReadableProperty, str]


CompletedResult = Annotated[
    KeyEventResult | PropertyQueryResult,
    Field(discriminator="operation"),
]


class CompletedResponse(ContractModel):
    version: Literal["1"]
    request_id: RequestId
    status: Literal["completed"]
    result: CompletedResult


class ErrorResponse(ContractModel):
    version: Literal["1"]
    request_id: RequestId
    status: Literal["error"]
    error: ErrorCode
    message: ErrorMessage
    retry_after_ms: int | None = Field(default=None, strict=True, ge=1, le=60_000)


Response = Annotated[
    AcceptedResponse | CompletedResponse | ErrorResponse,
    Field(discriminator="status"),
]
response_adapter: TypeAdapter[Response] = TypeAdapter(Response)


class ContractPayloadError(ValueError):
    """Raised before model validation when the payload envelope is unsafe."""


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractPayloadError(f"duplicate field: {key}")
        value[key] = item
    return value


def parse_request(payload: bytes | str) -> Request:
    """Decode and validate one bounded JSON request from the parent process."""

    if not isinstance(payload, (bytes, str)):
        raise ContractPayloadError("payload must be bytes or a string")

    if isinstance(payload, bytes):
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise ContractPayloadError("payload exceeds byte limit")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractPayloadError("payload must be UTF-8") from exc
    else:
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ContractPayloadError("payload exceeds byte limit")
        text = payload

    try:
        decoded = json.loads(text, object_pairs_hook=_reject_duplicate_fields)
    except ContractPayloadError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractPayloadError("payload must be valid JSON") from exc

    if not isinstance(decoded, dict):
        raise ContractPayloadError("payload must be a JSON object")
    return Request.model_validate(decoded)
