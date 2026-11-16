from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)

from .schemas import DeviceConfig

MAX_SIDECAR_RESPONSE_BYTES = 16_384
CONTRACT_VERSION = "1"
ADB_PROPERTY_NAMES = (
    "ro.product.manufacturer",
    "ro.product.model",
    "ro.build.version.release",
    "ro.build.version.sdk",
)
ADB_KEY_MAP = {
    "BACK": "back",
    "DPAD_CENTER": "enter",
    "DPAD_DOWN": "dpad_down",
    "DPAD_LEFT": "dpad_left",
    "DPAD_RIGHT": "dpad_right",
    "DPAD_UP": "dpad_up",
    "HOME": "home",
    "MEDIA_PLAY_PAUSE": "media_play_pause",
    "VOLUME_DOWN": "volume_down",
    "VOLUME_MUTE": "volume_mute",
    "VOLUME_UP": "volume_up",
}

OpaqueTargetId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class AdbSidecarError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AdbSidecarConfigurationError(AdbSidecarError):
    pass


class AdbSidecarProtocolError(AdbSidecarError):
    pass


class _SnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["piphi.adb.snapshot.v1"]
    connected: bool
    authorized: bool
    lifecycle: str = Field(min_length=1, max_length=32)
    service_available: bool
    target_id: OpaqueTargetId | None
    device_manufacturer: str | None = Field(default=None, max_length=256)
    device_model: str | None = Field(default=None, max_length=256)
    android_release: str | None = Field(default=None, max_length=64)
    android_sdk: str | None = Field(default=None, max_length=16)
    queue_depth: int = Field(ge=0, le=100)
    queue_capacity: int = Field(ge=1, le=100)
    queue_high_water_mark: int = Field(ge=0, le=100)
    reconnect_count: int = Field(ge=0)
    request_success_count: int = Field(ge=0)
    request_failure_count: int = Field(ge=0)
    timeout_count: int = Field(ge=0)
    transport_error_count: int = Field(ge=0)
    operation_duration_ms: float | None = Field(default=None, ge=0)
    last_error_code: str | None = Field(default=None, max_length=64)
    config_id: str = Field(min_length=1, max_length=128)


class _PropertyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["property_query"]
    properties: dict[str, str]


class _KeyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["key_event"]
    repeats_completed: int = Field(ge=1, le=10)


class _CompletedPropertyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed"]
    result: _PropertyResult


class _CompletedKeyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed"]
    result: _KeyResult


class _ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal["1"]
    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["error"]
    error: Literal["unauthorized", "offline", "timeout", "queue_full", "unsupported"]
    message: str = Field(min_length=1, max_length=256)
    retry_after_ms: int | None = Field(default=None, ge=0, le=60_000)


_PROPERTY_RESPONSE: TypeAdapter[_CompletedPropertyResponse | _ErrorResponse] = TypeAdapter(
    _CompletedPropertyResponse | _ErrorResponse
)
_KEY_RESPONSE: TypeAdapter[_CompletedKeyResponse | _ErrorResponse] = TypeAdapter(
    _CompletedKeyResponse | _ErrorResponse
)


@dataclass(frozen=True, slots=True)
class AdbDeviceSnapshot:
    connected: bool
    authorized: bool
    manufacturer: str | None
    model: str | None
    android_release: str | None
    android_sdk: str | None
    queue_depth: int
    queue_capacity: int
    reconnect_count: int
    timeout_count: int
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class _TargetLease:
    target_id: str


class AdbSidecarClient:
    """Authenticated, bounded client for the private Android ADB sidecar API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("PIPHI_ANDROID_ADB_SIDECAR_URL")
            or "http://piphi-android-adb-sidecar:4213"
        ).rstrip("/")
        self.token = str(
            token
            or os.getenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN")
            or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
            or ""
        ).strip()
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(15.0),
        )
        self._owns_client = client is None
        self._targets: dict[str, _TargetLease] = {}

    async def configure(self, config: DeviceConfig) -> AdbDeviceSnapshot:
        if not self.token:
            raise AdbSidecarConfigurationError(
                "authentication_not_configured",
                "ADB sidecar authentication is not configured",
            )
        config_id = str(config.config_id or config.id)
        await self._request_json(
            "POST",
            "/config",
            payload={
                "id": config_id,
                "host": config.host,
                "port": config.adb_port,
                "alias": config.alias,
                "queue_capacity": config.adb_queue_capacity,
                "connect_timeout_ms": config.adb_connect_timeout_ms,
                "operation_timeout_ms": config.adb_operation_timeout_ms,
            },
        )
        try:
            raw_snapshot = await self._request_json(
                "GET",
                "/v1/adb/snapshot",
                params={"config_id": config_id},
            )
            try:
                snapshot = _SnapshotResponse.model_validate(raw_snapshot)
            except ValidationError as exc:
                raise AdbSidecarProtocolError(
                    "invalid_snapshot",
                    "ADB sidecar returned an invalid snapshot",
                ) from exc
            if not snapshot.connected or not snapshot.authorized or snapshot.target_id is None:
                raise AdbSidecarConfigurationError(
                    "target_not_ready",
                    "ADB target is not connected and authorized",
                )
        except Exception:
            await self._best_effort_deconfigure(config_id)
            raise
        self._targets[config_id] = _TargetLease(target_id=snapshot.target_id)
        return self._snapshot(snapshot)

    async def refresh(self, config_id: str, *, timeout_ms: int) -> AdbDeviceSnapshot:
        # A property query is idempotent. Reacquire a lease before issuing it so
        # a sidecar restart can recover without replaying a command.
        before = await self.snapshot(config_id, reacquire=True)
        properties = await self._execute(
            config_id,
            timeout_ms=timeout_ms,
            command={
                "operation": "property_query",
                "properties": list(ADB_PROPERTY_NAMES),
            },
            adapter=_PROPERTY_RESPONSE,
        )
        assert isinstance(properties, _CompletedPropertyResponse)
        values = properties.result.properties
        if set(values) != set(ADB_PROPERTY_NAMES):
            raise AdbSidecarProtocolError(
                "invalid_property_result",
                "ADB sidecar returned an incomplete property result",
            )
        return AdbDeviceSnapshot(
            connected=before.connected,
            authorized=before.authorized,
            manufacturer=values["ro.product.manufacturer"] or None,
            model=values["ro.product.model"] or None,
            android_release=values["ro.build.version.release"] or None,
            android_sdk=values["ro.build.version.sdk"] or None,
            queue_depth=before.queue_depth,
            queue_capacity=before.queue_capacity,
            reconnect_count=before.reconnect_count,
            timeout_count=before.timeout_count,
            last_error_code=before.last_error_code,
        )

    async def send_key(self, config_id: str, key: str, *, timeout_ms: int) -> None:
        normalized = key.strip().upper()
        sidecar_key = ADB_KEY_MAP.get(normalized)
        if sidecar_key is None:
            raise ValueError("Android TV key is not supported by ADB transport")
        # Reacquiring before the event is safe. Once execute starts, any failure
        # is returned to the caller and the event is never retried.
        await self.snapshot(config_id, reacquire=True)
        response = await self._execute(
            config_id,
            timeout_ms=timeout_ms,
            command={"operation": "key_event", "key": sidecar_key, "repeat": 1},
            adapter=_KEY_RESPONSE,
        )
        assert isinstance(response, _CompletedKeyResponse)
        if response.result.repeats_completed != 1:
            raise AdbSidecarProtocolError(
                "invalid_key_result",
                "ADB sidecar returned an invalid key completion count",
            )

    async def snapshot(
        self,
        config_id: str,
        *,
        reacquire: bool = False,
    ) -> AdbDeviceSnapshot:
        if not reacquire:
            self._require_target(config_id)
        raw = await self._request_json(
            "GET",
            "/v1/adb/snapshot",
            params={"config_id": config_id},
        )
        try:
            response = _SnapshotResponse.model_validate(raw)
        except ValidationError as exc:
            raise AdbSidecarProtocolError(
                "invalid_snapshot",
                "ADB sidecar returned an invalid snapshot",
            ) from exc
        if response.config_id != config_id:
            raise AdbSidecarProtocolError(
                "config_id_mismatch",
                "ADB sidecar snapshot did not match the configuration",
            )
        if not response.connected or not response.authorized or response.target_id is None:
            raise AdbSidecarError(
                "unauthorized" if not response.authorized else "offline",
                "ADB target authorization is required"
                if not response.authorized
                else "ADB target is offline",
            )
        current = self._targets.get(config_id)
        if current is None or current.target_id != response.target_id:
            if not reacquire:
                raise AdbSidecarProtocolError(
                    "target_lease_changed",
                    "ADB target lease changed unexpectedly",
                )
            self._targets[config_id] = _TargetLease(target_id=response.target_id)
        return self._snapshot(response)

    async def remove(self, config_id: str) -> bool:
        existed = self._targets.pop(config_id, None) is not None
        await self._request_json(
            "POST",
            "/deconfigure",
            payload={"config_id": config_id},
        )
        return existed

    async def close(self) -> None:
        self._targets.clear()
        if self._owns_client:
            await self._client.aclose()

    async def _execute(
        self,
        config_id: str,
        *,
        timeout_ms: int,
        command: dict[str, Any],
        adapter: TypeAdapter[Any],
    ) -> Any:
        target = self._require_target(config_id)
        request_id = f"adb-{secrets.token_hex(16)}"
        raw = await self._request_json(
            "POST",
            "/v1/adb/execute",
            payload={
                "version": CONTRACT_VERSION,
                "request_id": request_id,
                "target": {"target_id": target.target_id},
                "timeout_ms": timeout_ms,
                "command": command,
            },
            timeout_seconds=(timeout_ms / 1000) + 1.0,
        )
        try:
            response = adapter.validate_python(raw)
        except ValidationError as exc:
            raise AdbSidecarProtocolError(
                "invalid_execute_response",
                "ADB sidecar returned an invalid execute response",
            ) from exc
        if response.request_id != request_id:
            raise AdbSidecarProtocolError(
                "request_id_mismatch",
                "ADB sidecar response did not match the request",
            )
        if isinstance(response, _ErrorResponse):
            raise AdbSidecarError(response.error, self._public_error_message(response.error))
        return response

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> Any:
        if not self.token:
            raise AdbSidecarConfigurationError(
                "authentication_not_configured",
                "ADB sidecar authentication is not configured",
            )
        request = self._client.build_request(
            method,
            path,
            json=payload,
            params=params,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=timeout_seconds,
        )
        try:
            response = await self._client.send(request, stream=True)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AdbSidecarError("offline", "ADB sidecar is unavailable") from exc
        try:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_SIDECAR_RESPONSE_BYTES:
                    raise AdbSidecarProtocolError(
                        "response_too_large",
                        "ADB sidecar response exceeded the byte limit",
                    )
        finally:
            await response.aclose()
        if response.status_code >= 400:
            code = "unauthorized" if response.status_code == 401 else "sidecar_request_failed"
            raise AdbSidecarError(code, "ADB sidecar request failed")
        try:
            return json.loads(body.decode("utf-8"), object_pairs_hook=self._unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdbSidecarProtocolError(
                "invalid_json",
                "ADB sidecar returned an invalid response",
            ) from exc

    async def _best_effort_deconfigure(self, config_id: str) -> None:
        try:
            await self._request_json(
                "POST",
                "/deconfigure",
                payload={"config_id": config_id},
            )
        except AdbSidecarError:
            pass

    def _require_target(self, config_id: str) -> _TargetLease:
        target = self._targets.get(config_id)
        if target is None:
            raise AdbSidecarConfigurationError(
                "unknown_target",
                "ADB target is not configured",
            )
        return target

    @staticmethod
    def _snapshot(response: _SnapshotResponse) -> AdbDeviceSnapshot:
        return AdbDeviceSnapshot(
            connected=response.connected,
            authorized=response.authorized,
            manufacturer=response.device_manufacturer,
            model=response.device_model,
            android_release=response.android_release,
            android_sdk=response.android_sdk,
            queue_depth=response.queue_depth,
            queue_capacity=response.queue_capacity,
            reconnect_count=response.reconnect_count,
            timeout_count=response.timeout_count,
            last_error_code=response.last_error_code,
        )

    @staticmethod
    def _public_error_message(code: str) -> str:
        return {
            "unauthorized": "ADB target authorization is required",
            "offline": "ADB target is offline",
            "timeout": "ADB target request timed out",
            "queue_full": "ADB target command queue is full",
            "unsupported": "ADB target operation is unsupported",
        }[code]

    @staticmethod
    def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise json.JSONDecodeError("duplicate field", key, 0)
            result[key] = value
        return result
