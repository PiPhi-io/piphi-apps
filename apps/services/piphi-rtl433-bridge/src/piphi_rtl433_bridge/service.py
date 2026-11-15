from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import os
import secrets
from typing import Callable

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from .bridge import Rtl433Bridge
from .config import BridgeConfig, load_bridge_config, reconfigure_bridge_config


class RadioConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: str | None = None
    rtlsdr_device: str | None = None
    receiver_gain: str | None = None
    rtl433_protocols: str | None = None


class BridgeSupervisor:
    def __init__(
        self,
        config: BridgeConfig,
        *,
        bridge_factory: Callable[[BridgeConfig], Rtl433Bridge] = Rtl433Bridge,
    ) -> None:
        self.config = config
        self._bridge_factory = bridge_factory
        self._task: asyncio.Task[None] | None = None
        self._bridge: Rtl433Bridge | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            self._start_unlocked()

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_unlocked()

    async def configure(self, payload: RadioConfigurationRequest) -> BridgeConfig:
        async with self._lock:
            next_config = reconfigure_bridge_config(
                self.config,
                frequency=_clean_optional(payload.frequency),
                rtl_sdr_device=_clean_optional(payload.rtlsdr_device),
                receiver_gain=_clean_optional(payload.receiver_gain),
                protocol_ids_text=_clean_optional(payload.rtl433_protocols),
            )
            if next_config == self.config:
                return self.config
            await self._stop_unlocked()
            self.config = next_config
            self._start_unlocked()
            return self.config

    def _start_unlocked(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._bridge = self._bridge_factory(self.config)
        self._task = asyncio.create_task(self._bridge.run_forever())

    async def _stop_unlocked(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        self._bridge = None

    def health(self) -> dict[str, object]:
        running = self._task is not None and not self._task.done()
        bridge = self._bridge
        return {
            "status": "ok" if running else "degraded",
            "process_supervisor_running": running,
            "forwarded_count": bridge.forwarded_count if bridge else 0,
            "invalid_line_count": bridge.invalid_line_count if bridge else 0,
            "dropped_count": bridge.dropped_count if bridge else 0,
            "duplicate_count": bridge.duplicate_count if bridge else 0,
            "retry_count": bridge.retry_count if bridge else 0,
            "failed_count": bridge.failed_count if bridge else 0,
            **_public_config(self.config),
        }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


supervisor = BridgeSupervisor(load_bridge_config())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await supervisor.start()
    try:
        yield
    finally:
        await supervisor.stop()


app = FastAPI(title="PiPhi rtl_433 Radio Bridge", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return supervisor.health()


@app.post("/radio/config")
async def configure_radio(
    payload: RadioConfigurationRequest,
    x_piphi_service_token: str | None = Header(default=None),
) -> dict[str, object]:
    _authorize_service_request(x_piphi_service_token)
    try:
        config = await supervisor.configure(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "listening", **_public_config(config)}


def _authorize_service_request(received_token: str | None) -> None:
    expected_token = str(os.getenv("PIPHI_SERVICE_AUTH_TOKEN") or "").strip()
    production = str(os.getenv("PIPHI_ENV") or os.getenv("ENVIRONMENT") or "").lower() == "production"
    if not expected_token:
        if production:
            raise HTTPException(status_code=503, detail="Radio service authentication is not configured")
        return
    if not received_token or not secrets.compare_digest(received_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid radio service authentication")


def _public_config(config: BridgeConfig) -> dict[str, object]:
    return {
        "frequency": config.frequency,
        "rtlsdr_device": config.rtl_sdr_device,
        "receiver_gain": config.receiver_gain,
        "rtl433_protocols": list(config.protocol_ids),
    }


def runtime_port() -> int:
    import os
    raw_port = os.getenv("PORT")
    try:
        port = 8091 if raw_port is None else int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=runtime_port())


if __name__ == "__main__":
    main()
