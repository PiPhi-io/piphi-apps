from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import os
import secrets
import time
from collections import OrderedDict, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_config_apply_response,
    build_config_remove_response,
    build_local_event_record,
    create_runtime_starter,
    schedule_telemetry_delivery,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_payload,
    sync_runtime_auth_from_fastapi_request,
)

from .tesla import (
    FLEET_API_BASE_URLS,
    TeslaAPIError,
    TeslaClient,
    normalize_summary_state,
    normalize_vehicle_data_state,
    telemetry_metrics,
)


INTEGRATION_ID = "piphi-network-tesla-ev"
INTEGRATION_NAME = "PiPhi Network Tesla EV"
INTEGRATION_VERSION = "0.2.0"
PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT.parent
MANIFEST_PATH = (
    PACKAGE_ROOT / "manifest.json"
    if (PACKAGE_ROOT / "manifest.json").exists()
    else SOURCE_ROOT / "manifest.json"
)
BEHAVIORS_PATH = (
    PACKAGE_ROOT / "behaviors.json"
    if (PACKAGE_ROOT / "behaviors.json").exists()
    else SOURCE_ROOT / "behaviors.json"
)
LEDGER_PATH = Path(
    os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "/.piphinetwork/automation-actions.sqlite3")
)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(LEDGER_PATH)
)

SUPPORTED_COMMANDS = {"refresh", "wake_up"}
COMMAND_ALIASES = {
    "tesla.refresh": "refresh",
    "refresh_readings": "refresh",
}
SUPPORTED_CAPABILITIES = {
    "action.refresh",
    "action.wake_up",
    "device.refresh",
    "tesla.refresh",
    "tesla.vehicle_state",
    "tesla.wake",
}

SENSITIVE_KEYS = {
    "access_token", "accessToken", "refresh_token", "refreshToken", "authorization",
    "vin", "latitude", "longitude", "heading", "headingDegrees", "speedMph", "summary", "config",
}
DISCOVERY_HANDLE_TTL_SECONDS = 300.0
DISCOVERY_HANDLE_MAX_ENTRIES = 256


def _opaque_id(value: str) -> str:
    salt = os.getenv("PIPHI_IDENTITY_SALT", INTEGRATION_ID)
    return "tesla-" + hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:20]


def _credential_fingerprint(access_token: str) -> str:
    return hashlib.sha256(access_token.encode()).hexdigest()


class DiscoveryHandleStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = DISCOVERY_HANDLE_TTL_SECONDS,
        max_entries: int = DISCOVERY_HANDLE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Discovery handle limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock
        self.entries: OrderedDict[str, tuple[str, str, str, float]] = OrderedDict()

    def _purge_expired(self) -> None:
        now = self.clock()
        for handle, entry in list(self.entries.items()):
            if entry[3] <= now:
                self.entries.pop(handle, None)

    def issue(self, *, vin: str, access_token: str, region: str) -> str:
        self._purge_expired()
        while len(self.entries) >= self.max_entries:
            self.entries.popitem(last=False)
        handle = "discovery-" + secrets.token_urlsafe(24)
        self.entries[handle] = (
            vin,
            _credential_fingerprint(access_token),
            region,
            self.clock() + self.ttl_seconds,
        )
        return handle

    def resolve(self, handle: str, *, access_token: str, region: str) -> str:
        self._purge_expired()
        entry = self.entries.get(handle)
        if entry is None:
            raise ValueError("Invalid or expired vehicle_ref")
        vin, fingerprint, issued_region, _expires_at = entry
        if not hmac.compare_digest(fingerprint, _credential_fingerprint(access_token)) or issued_region != region:
            raise ValueError("vehicle_ref does not match these credentials and region")
        self.entries.pop(handle, None)
        return vin

    def clear(self) -> None:
        self.entries.clear()

    def __len__(self) -> int:
        self._purge_expired()
        return len(self.entries)


discovery_handles = DiscoveryHandleStore()


def redact(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return "***"
    if isinstance(value, dict):
        return {key: "***" if key in SENSITIVE_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


class RequestBudgetExceeded(RuntimeError):
    pass


class AccountCoordinator:
    def __init__(self) -> None:
        self.locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.ledger: dict[str, dict[str, Any]] = {}

    def account_key(self, config: dict[str, Any]) -> str:
        token = config["access_token"]
        secret = token.get_secret_value() if isinstance(token, SecretStr) else str(token)
        return hashlib.sha256(secret.encode()).hexdigest()

    def record(self, config: dict[str, Any], kind: str) -> None:
        key = self.account_key(config)
        today = date.today().isoformat()
        item = self.ledger.setdefault(key, {"day": today, "requests": 0, "live": 0, "wakes": 0, "last_wake": {}})
        if item["day"] != today:
            item.update({"day": today, "requests": 0, "live": 0, "wakes": 0, "last_wake": {}})
        limits = {
            "requests": int(config.get("request_budget_per_day", 100)),
            "live": int(config.get("live_data_budget_per_day", 48)),
            "wakes": int(config.get("wake_budget_per_day", 2)),
        }
        if item["requests"] >= limits["requests"]:
            raise RequestBudgetExceeded("daily_request_budget_exhausted")
        if kind == "live" and item["live"] >= limits["live"]:
            raise RequestBudgetExceeded("daily_live_data_budget_exhausted")
        if kind == "wake":
            if item["wakes"] >= limits["wakes"]:
                raise RequestBudgetExceeded("daily_wake_budget_exhausted")
            last = item["last_wake"].get(config["device_id"])
            if last and datetime.now(UTC) - last < timedelta(minutes=int(config.get("wake_cooldown_minutes", 30))):
                raise RequestBudgetExceeded("wake_cooldown_active")
            item["last_wake"][config["device_id"]] = datetime.now(UTC)
        item["requests"] += 1
        if kind in {"live", "wake"}:
            item["live" if kind == "live" else "wakes"] += 1

    def public_counters(self, config: dict[str, Any]) -> dict[str, Any]:
        item = self.ledger.get(self.account_key(config), {})
        return {key: item.get(key, 0) for key in ("requests", "live", "wakes")}


coordinator = AccountCoordinator()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _payload_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bounded_int(payload: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    vehicle_ref = _string(payload.get("vehicle_ref"))
    region = _string(payload.get("region")) or "na"
    if region not in {"na", "eu", "cn"}:
        raise ValueError(f"Unsupported Tesla Fleet API region: {region}")
    token = _string(payload.get("access_token"))
    vin = _string(payload.get("vin"))
    if not vin and vehicle_ref:
        if not token:
            raise ValueError("Missing required access_token")
        vin = discovery_handles.resolve(vehicle_ref, access_token=token, region=region)
    vin = vin or ""
    config_id = (
        _string(payload.get("configId"))
        or _string(payload.get("config_id"))
        or _string(payload.get("id"))
        or (f"cfg-{_opaque_id(vin)}" if vin else None)
        or ""
    )
    return {
        "id": config_id,
        "configId": config_id,
        "config_id": config_id,
        "containerId": _string(payload.get("containerId")) or _string(payload.get("container_id")),
        "integrationId": _string(payload.get("integrationId")) or _string(payload.get("integration_id")),
        "vin": vin,
        "vehicle_ref": vehicle_ref or (_opaque_id(vin) if vin else ""),
        "device_id": _opaque_id(vin) if vin else "",
        "access_token": SecretStr(token or ""),
        "region": region,
        "vehicle_name": _string(payload.get("vehicle_name")),
        "include_location": payload.get("include_location") is True,
        "read_only": payload.get("read_only") is not False,
        "enable_wake": payload.get("enable_wake") is True,
        "request_budget_per_day": _bounded_int(payload, "request_budget_per_day", 100, 1, 1000),
        "live_data_budget_per_day": _bounded_int(payload, "live_data_budget_per_day", 48, 1, 500),
        "wake_budget_per_day": _bounded_int(payload, "wake_budget_per_day", 2, 0, 3),
        "wake_cooldown_minutes": _bounded_int(payload, "wake_cooldown_minutes", 30, 10, 1440),
    }


def _client(config: dict[str, Any]) -> TeslaClient:
    return TeslaClient(
        access_token=config["access_token"],
        region=str(config.get("region") or "na"),
    )


def append_event(
    event_type: str,
    *,
    config_id: str | None = None,
    device_id: str | None = None,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        source=INTEGRATION_ID,
        severity=severity,
        device={"config_id": config_id, "device_id": device_id},
        payload=redact(payload or {}),
    )
    registry.append_event(event)
    return event


def _entry(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_id": config["configId"],
        "configId": config["configId"],
        "device_id": state["deviceId"],
        "deviceId": state["deviceId"],
        "display_name": state["displayName"],
        "region": state["region"],
        "container_id": config.get("containerId"),
        "integration_id": config.get("integrationId") or INTEGRATION_ID,
        "config": config,
        "latest_state": state,
        "last_updated": _now(),
    }


async def deliver_telemetry(entry: dict[str, Any], state: dict[str, Any]) -> None:
    metrics, units = telemetry_metrics(state)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units=units,
    )


def _failure_category(exc: Exception) -> tuple[str, bool, int]:
    if isinstance(exc, TeslaAPIError):
        status = 401 if exc.category == "authentication_required" else (exc.status_code or 503)
        return exc.category, exc.retryable, status
    if isinstance(exc, RequestBudgetExceeded):
        return str(exc), False, 429
    if isinstance(exc, ValueError):
        return "invalid_request", False, 400
    return "integration_unavailable", False, 503


def _degraded_state(state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    category, _, _ = _failure_category(exc)
    vehicle_state = "auth_failed" if category in {"authentication_required", "scope_or_consent_denied"} else (
        "rate_limited" if category in {"rate_limited", "daily_request_budget_exhausted", "daily_live_data_budget_exhausted"} else "unavailable"
    )
    return {**state, "online": False, "reachable": False, "vehicleState": vehicle_state, "errorCategory": category, "dataQuality": "last_known" if state.get("lastRefreshAt") else "unavailable", "stale": True}


async def refresh_entry(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise RuntimeError(f"Unknown Tesla config: {config_id}")
    config = entry["config"]
    client = _client(config)
    try:
        async with coordinator.locks[coordinator.account_key(config)]:
            coordinator.record(config, "summary")
            summary = await client.vehicle_summary(str(config["vin"]))
            state = normalize_summary_state(config, summary, entry.get("latest_state"))
            if summary.get("state") == "online":
                coordinator.record(config, "live")
                state = normalize_vehicle_data_state(config, summary, await client.vehicle_data(str(config["vin"])))
    except Exception as exc:
        state = _degraded_state(entry["latest_state"], exc)
        registry.set(config_id, {**entry, "latest_state": state, "last_updated": _now()})
        registry.update_state(config_id, state, device_id=state["deviceId"])
        append_event("tesla.refresh.failed", config_id=config_id, device_id=state["deviceId"], severity="warning", payload={"error_category": state["errorCategory"]})
        raise
    updated = {**entry, "display_name": state["displayName"], "latest_state": state, "last_updated": _now()}
    registry.set(config_id, updated)
    registry.update_state(config_id, state, device_id=state["deviceId"])
    append_event(
        "tesla.vehicle.refreshed",
        config_id=config_id,
        device_id=state["deviceId"],
        payload={"vehicle_state": state["vehicleState"], "source": state["source"]},
    )
    try:
        await deliver_telemetry(updated, state)
    except Exception as exc:
        state = _degraded_state(state, exc)
        updated = {**updated, "latest_state": state}
        registry.set(config_id, updated)
        registry.update_state(config_id, state, device_id=state["deviceId"])
        append_event(
            "tesla.telemetry.delivery_failed",
            config_id=config_id,
            device_id=state["deviceId"],
            severity="warning",
            payload={"error_category": _failure_category(exc)[0]},
        )
    return registry.get(config_id) or updated


async def refresh_all_state() -> None:
    for config_id in registry.ids():
        try:
            await refresh_entry(config_id)
        except Exception as exc:
            entry = registry.get(config_id)
            if entry:
                state = _degraded_state(entry["latest_state"], exc)
                registry.set(config_id, {**entry, "latest_state": state})
                registry.update_state(config_id, state, device_id=state["deviceId"])


starter.state.provide(refresh_all_state, source=INTEGRATION_ID)


async def apply_config(config: dict[str, Any]) -> dict[str, Any]:
    if not config["vin"]:
        raise ValueError("Missing required vin")
    if not config["access_token"].get_secret_value():
        raise ValueError("Missing required access_token")
    async with coordinator.locks[coordinator.account_key(config)]:
        coordinator.record(config, "summary")
        summary = await _client(config).vehicle_summary(str(config["vin"]))
    state = normalize_summary_state(config, summary)
    entry = _entry(config, state)
    registry.set(config["configId"], entry)
    registry.update_state(config["configId"], state, device_id=state["deviceId"])
    append_event(
        "tesla.config.applied",
        config_id=config["configId"],
        device_id=state["deviceId"],
        payload={"vehicle_name": state["displayName"], "region": state["region"]},
    )
    try:
        await refresh_entry(config["configId"])
    except Exception as exc:
        degraded = _degraded_state(state, exc)
        registry.set(config["configId"], {**entry, "latest_state": degraded})
        registry.update_state(config["configId"], degraded, device_id=state["deviceId"])
        append_event(
            "tesla.refresh.degraded",
            config_id=config["configId"],
            device_id=state["deviceId"],
            severity="warning",
            payload={"error_category": _failure_category(exc)[0]},
        )
    return registry.get(config["configId"]) or entry


def remove_config(config_id: str) -> bool:
    removed = registry.remove(config_id)
    if removed:
        append_event(
            "tesla.config.removed",
            config_id=config_id,
            device_id=removed.get("device_id"),
            payload={},
        )
    return removed is not None


def resolve_config_id(payload: dict[str, Any]) -> str:
    target = _payload_dict(payload.get("target"))
    config_id = (
        _string(payload.get("configId"))
        or _string(payload.get("config_id"))
        or _string(target.get("config_id"))
    )
    if config_id:
        return config_id
    primary = registry.primary_entry()
    if primary:
        return str(primary["config_id"])
    raise RuntimeError("No Tesla config is active")


def validate_capabilities(payload: dict[str, Any]) -> None:
    requested = [payload.get("capability")]
    requirements = payload.get("capability_requirements") or payload.get("capabilityRequirements")
    if isinstance(requirements, list):
        requested.extend(requirements)
    unsupported = [str(item) for item in requested if item and str(item) not in SUPPORTED_CAPABILITIES]
    if unsupported:
        raise ValueError(f"Unsupported capability: {unsupported[0]}")


async def execute_action(action: AutomationActionRequest) -> AutomationActionResult:
    extras = action.model_extra or {}
    payload = {**extras, "config_id": action.config_id, "device_id": action.device_id}
    try:
        config_id = resolve_config_id(payload)
        entry = registry.get(config_id)
        if entry is None:
            raise RuntimeError(f"Unknown Tesla config: {config_id}")
        if action.command == "refresh":
            refreshed = await refresh_entry(config_id)
            state = refreshed["latest_state"]
        elif action.command == "wake_up":
            config = entry["config"]
            if config.get("read_only", True) or not config.get("enable_wake", False):
                raise ValueError("wake_disabled_read_only")
            if action.args.get("confirm_wake") is not True:
                raise ValueError("wake_requires_explicit_confirmation")
            client = _client(config)
            async with coordinator.locks[coordinator.account_key(config)]:
                coordinator.record(config, "wake")
                summary = await client.wake(str(config["vin"]))
                for _attempt in range(6):
                    if summary.get("state") == "online":
                        break
                    await asyncio.sleep(10)
                    coordinator.record(config, "summary")
                    summary = await client.vehicle_summary(str(config["vin"]))
            state = {
                **normalize_summary_state(config, summary, entry.get("latest_state")),
                "lastCommandAt": _now(),
            }
            registry.set(config_id, {**entry, "latest_state": state, "last_updated": _now()})
            registry.update_state(config_id, state, device_id=entry["device_id"])
            append_event(
                "tesla.vehicle.woken",
                config_id=config_id,
                device_id=entry["device_id"],
                payload={"vehicle_state": state["vehicleState"]},
            )
        else:
            raise RuntimeError(f"Unsupported command: {action.command}")
    except Exception as exc:
        category, retryable, status_code = _failure_category(exc)
        return AutomationActionResult.failure(
            category, retryable=retryable, metadata={"status_code": status_code, "error_category": category}
        )
    target = extras.get("target") if isinstance(extras.get("target"), dict) else {}
    return AutomationActionResult.success(
        {
            "ok": True,
            "command": action.command,
            "contract_version": extras.get("contract_version"),
            "configId": config_id,
            "target": target,
            "params": action.args,
            "state": state,
        }
    )


for _registered_command in sorted(SUPPORTED_COMMANDS):
    automation_registry.action(_registered_command)(execute_action)


def create_app() -> FastAPI:
    application = FastAPI(title=INTEGRATION_NAME, version=INTEGRATION_VERSION)

    @application.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"ok": False, "reason": str(exc)})

    @application.exception_handler(TeslaAPIError)
    async def tesla_error_handler(_request: Request, exc: TeslaAPIError) -> JSONResponse:
        _, _, status_code = _failure_category(exc)
        return JSONResponse(status_code=status_code, content={"ok": False, "error_category": exc.category, "retryable": exc.retryable})

    @application.get("/health")
    async def health() -> Any:
        return starter.health_response(
            metadata={"active_configs": len(registry.ids())}
        )

    @application.get("/diagnostics")
    async def diagnostics() -> Any:
        return starter.diagnostics_response(
            diagnostics={
                "active_config_count": len(registry.ids()),
                "recent_event_count": len(registry.recent_events),
                "vehicles": [
                    {
                        "vehicle_handle": entry.get("device_id"),
                        "region": entry.get("region"),
                        "state": entry.get("latest_state", {}).get("vehicleState"),
                        "data_quality": entry.get("latest_state", {}).get("dataQuality"),
                        "last_refresh_at": entry.get("latest_state", {}).get("lastRefreshAt"),
                        "error_category": entry.get("latest_state", {}).get("errorCategory"),
                        "budget": coordinator.public_counters(entry["config"]),
                    }
                    for entry in registry.entries.values()
                ],
            }
        )

    @application.get("/manifest.json")
    async def manifest() -> dict[str, Any]:
        return _manifest()

    @application.get("/behaviors.json")
    async def behaviors() -> Any:
        return json.loads(BEHAVIORS_PATH.read_text(encoding="utf-8"))

    @application.get("/ui-config")
    @application.get("/ui")
    async def ui() -> dict[str, Any]:
        manifest_payload = _manifest()
        return {
            "schema": manifest_payload["config"]["schema"],
            "uiSchema": {
                "access_token": {"ui:widget": "password"},
                "read_only": {"ui:disabled": True},
            },
        }

    async def discover_payload(access_token: str, region: str) -> dict[str, Any]:
        if region not in FLEET_API_BASE_URLS:
            raise ValueError(f"Unsupported Tesla Fleet API region: {region}")
        vehicles = await TeslaClient(SecretStr(access_token), region).list_vehicles()
        discovered: list[dict[str, Any]] = []
        for item in vehicles:
            vin = str(item.get("vin") or "")
            if not vin:
                continue
            handle = discovery_handles.issue(vin=vin, access_token=access_token, region=region)
            discovered.append(
                {
                    "id": _opaque_id(vin),
                    "deviceId": _opaque_id(vin),
                    "display_name": item.get("display_name") or "Tesla vehicle",
                    "state": item.get("state") or "unknown",
                    "region": region,
                    "suggested_config": {"vehicle_ref": handle, "region": region},
                }
            )
        return {
            "devices": discovered
        }

    @application.get("/discover")
    @application.get("/discovery")
    async def discover_get() -> Any:
        raise HTTPException(status_code=405, detail="Use POST discovery so credentials are not placed in URLs")

    @application.post("/discover")
    @application.post("/discovery")
    async def discover_post(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        inputs = _payload_dict(payload.get("inputs")) or payload
        access_token = _string(inputs.get("access_token"))
        if not access_token:
            raise ValueError("Missing access_token for discovery")
        region = _string(inputs.get("region")) or "na"
        return await discover_payload(access_token, region)

    @application.post("/config")
    async def configure(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        config = normalize_config(payload)
        entry = await apply_config(config)
        return build_config_apply_response(
            config_id=config["configId"],
            container_id=config.get("containerId"),
            metadata={
                "vehicle_handle": entry["device_id"],
                "vehicle_name": entry["display_name"],
                "region": entry["region"],
                "read_only": config["read_only"],
            },
        )

    @application.post("/configs/sync")
    @application.post("/config/sync")
    async def sync_configs(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
        active = set(registry.ids())
        applied: list[str] = []
        for raw in payload.get("configs") if isinstance(payload.get("configs"), list) else []:
            if not isinstance(raw, dict):
                continue
            config = normalize_config(raw)
            if not config["vin"] or not config["access_token"].get_secret_value():
                continue
            await apply_config(config)
            applied.append(config["configId"])
            active.discard(config["configId"])
        removed = [config_id for config_id in active if remove_config(config_id)]
        return {
            "ok": True,
            "generation": payload.get("generation") if isinstance(payload.get("generation"), int) else None,
            "applied_config_ids": applied,
            "removed_config_ids": removed,
            "skipped_config_ids": [],
        }

    @application.post("/deconfigure")
    async def deconfigure(payload: dict[str, Any]) -> Any:
        config_id = _string(payload.get("configId")) or _string(payload.get("config_id"))
        if not config_id:
            raise ValueError("Missing configId")
        return build_config_remove_response(config_id=config_id, removed=remove_config(config_id))

    @application.post("/deconfigure/{config_id}")
    async def deconfigure_path(config_id: str) -> Any:
        return build_config_remove_response(config_id=config_id, removed=remove_config(config_id))

    @application.get("/state")
    async def state(
        refresh: bool = Query(default=False),
        refresh_request_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            state_payload = await starter.state.response(
                refresh=refresh,
                refresh_request_id=refresh_request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **state_payload,
            "summary": {"activeConfigCount": len(registry.ids()), "recentEventCount": len(registry.recent_events)},
            "entries": {
                config_id: {
                    "config_id": config_id,
                    "device_id": entry["device_id"],
                    "display_name": entry["display_name"],
                    "region": entry["region"],
                    "latest_state": redact(entry["latest_state"]),
                }
                for config_id, entry in registry.entries.items()
            },
            "stateSnapshots": redact(dict(registry.state_snapshots)),
        }

    @application.get("/events")
    async def events() -> dict[str, Any]:
        return {"events": list(registry.recent_events)}

    @application.get("/entities")
    async def entities() -> dict[str, Any]:
        manifest_payload = _manifest()
        values = []
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if not entry:
                continue
            capabilities = [
                key for key, value in manifest_payload["capabilities"].items()
                if value.get("kind") == "sensor"
                and (entry["latest_state"].get("includeLocation") or key not in {"latitude", "longitude", "heading_degrees"})
            ]
            values.append(
                {
                    "id": entry["device_id"],
                    "name": entry["display_name"],
                    "configId": config_id,
                    "deviceId": entry["device_id"],
                    "deviceType": "vehicle",
                    "deviceClass": "electric_vehicle",
                    "entityType": "sensor",
                    "capabilities": capabilities,
                    "dashboard": {"allowedWidgets": ["tile", "stat", "sensor-card", "status-list"], "defaultWidget": "tile", "recommendedWidgets": ["tile", "stat", "sensor-card"]},
                    "metadata": {"vehicle_handle": entry["device_id"], "region": entry["region"], "vehicle_state": entry["latest_state"].get("vehicleState"), "include_location": entry["latest_state"].get("includeLocation"), "data_quality": entry["latest_state"].get("dataQuality")},
                    "available_commands": ([{"id": "refresh", "label": "Refresh"}] + ([{"id": "wake_up", "label": "Wake Up"}] if not entry["config"].get("read_only", True) and entry["config"].get("enable_wake", False) else [])),
                }
            )
        return {"entities": values, "capabilities": manifest_payload["capabilities"], "commands": manifest_payload["commands"]}

    @application.post("/command")
    async def command(payload: dict[str, Any], request: Request) -> Any:
        sync_runtime_auth_from_fastapi_request(runtime, request)
        raw = _string(payload.get("command"))
        command_name = COMMAND_ALIASES.get(raw or "", raw or "")
        if not command_name:
            raise ValueError("Missing command")
        if command_name not in SUPPORTED_COMMANDS:
            raise ValueError(f"Unsupported command: {command_name}")
        validate_capabilities(payload)
        config_id = resolve_config_id(payload)
        entry = registry.get(config_id)
        params = payload.get("params") or payload.get("args") or {}
        result = await dispatch_automation_action_from_fastapi(
            automation_registry,
            request,
            {
                **payload,
                "command": command_name,
                "config_id": config_id,
                "device_id": payload.get("device_id") or (entry or {}).get("device_id"),
                "args": params if isinstance(params, dict) else {},
            },
        )
        if not result.ok:
            raise HTTPException(status_code=int(result.metadata.get("status_code") or 503), detail=result.error)
        return {**result.result, "replayed": result.replayed}

    @application.exception_handler(Exception)
    async def runtime_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "integration_unavailable", "reason": "A sanitized internal error was recorded"},
        )

    return application


app = create_app()
