from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .commissioning import permit_join_controller
from .coordinator_claims import CoordinatorClaimConflict, claim_store
from .mqtt_gateway import mqtt_gateway
from .state import runtime, sidecar_store
from .zigbee2mqtt_mqtt import Zigbee2MqttMqttClient


async def startup_sync(_runtime, _client) -> None:
    # Real integrations can fetch an existing config snapshot from Core here.
    return None


async def _renew_coordinator_claim() -> None:
    while True:
        await asyncio.sleep(10)
        identity = sidecar_store.coordinator_identity
        owner_id = sidecar_store.coordinator_owner_id
        generation = sidecar_store.coordinator_claim_generation
        if not identity or not owner_id or generation is None:
            continue
        try:
            renewed = claim_store.renew(identity, owner_id, generation)
        except (CoordinatorClaimConflict, OSError, ValueError) as exc:
            sidecar_store.last_error = f"Coordinator ownership fencing failed: {exc}"
            mqtt_gateway.stop()
        else:
            sidecar_store.coordinator_claim_generation = renewed.generation


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        claim_heartbeat = asyncio.create_task(_renew_coordinator_claim())
        try:
            yield
        finally:
            claim_heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await claim_heartbeat
            if sidecar_store.current_config:
                client = Zigbee2MqttMqttClient(mqtt=sidecar_store.current_config.mqtt)
                with suppress(Exception):
                    await permit_join_controller.close(
                        sidecar_store.current_config.mqtt,
                        client.permit_join,
                    )
            mqtt_gateway.stop()
            if sidecar_store.coordinator_identity and sidecar_store.coordinator_owner_id:
                claim_store.release(
                    sidecar_store.coordinator_identity,
                    sidecar_store.coordinator_owner_id,
                    sidecar_store.coordinator_claim_generation,
                )
                sidecar_store.coordinator_identity = None
                sidecar_store.coordinator_owner_id = None
                sidecar_store.coordinator_claim_generation = None
