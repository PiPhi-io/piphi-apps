from __future__ import annotations

from typing import Any

from piphi_runtime_kit_python import (
    RuntimeContext,
    RuntimeRegistry,
    create_runtime_starter,
    resolve_core_base_url,
)

from piphi_network_thinqconnect import __version__

INTEGRATION_ID = "lg-thinq-connect-api"
INTEGRATION_NAME = "LG ThinQ Connect"
INTEGRATION_VERSION = __version__
CORE_BASE_URL = resolve_core_base_url("http://127.0.0.1:31419")

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
    core_base_url=CORE_BASE_URL,
)
registry = starter.registry
runtime_context = starter.runtime
telemetry_client = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync


def get_runtime_context() -> RuntimeContext:
    return runtime_context


def get_registry() -> RuntimeRegistry[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return registry


def set_core_http_client(client) -> None:
    runtime_context.set_core_http_client(client)


def get_core_http_client():
    return runtime_context.process_state.core_http_client


def append_event(event: dict[str, Any]) -> dict[str, Any]:
    return registry.append_event(event)


def update_device_state(device_id: str, state: dict[str, Any]) -> dict[str, Any]:
    return registry.update_state(device_id, state)


def get_primary_device() -> dict[str, Any] | None:
    return registry.primary_entry()


def list_pending_background_tasks() -> list[Any]:
    return [task for task in runtime_context.process_state.background_tasks if not task.done()]
