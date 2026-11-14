from __future__ import annotations

import asyncio
import os
import pty
import socket
import sys
import tty
from uuid import uuid4
from pathlib import Path

import httpx
import pytest
import uvicorn
from piphi_runtime_kit_python import SQLiteAutomationIdempotencyStore

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT / "apps" / "integrations" / "piphi-network-modbus" / "src"))

from piphi_modbus_rtu_sidecar.main import app as sidecar_app  # noqa: E402
from piphi_modbus_rtu_sidecar.transport import frame_with_crc  # noqa: E402
from piphi_network_modbus.main import app as parent_app  # noqa: E402
from piphi_network_modbus.routes import commands as parent_command_routes  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def start_server(app, port: int) -> tuple[uvicorn.Server, asyncio.Task[None]]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            return server, task
        if task.done():
            await task
        await asyncio.sleep(0.01)
    raise TimeoutError("HTTP server did not start")


async def stop_server(server: uvicorn.Server, task: asyncio.Task[None]) -> None:
    server.should_exit = True
    await asyncio.wait_for(task, timeout=5)


class RTUDeviceSimulator:
    def __init__(self, master_fd: int) -> None:
        self.master_fd = master_fd
        self.relay_on = False
        self.bad_crc_once = False
        self.requests: list[bytes] = []
        self._stopped = False

    async def run(self) -> None:
        buffer = b""
        while not self._stopped:
            try:
                chunk = await asyncio.to_thread(os.read, self.master_fd, 256)
            except OSError:
                return
            if not chunk:
                await asyncio.sleep(0.01)
                continue
            buffer += chunk
            while len(buffer) >= 8:
                request, buffer = buffer[:8], buffer[8:]
                self.requests.append(request)
                unit, function = request[0], request[1]
                if (unit, function, request[2:6]) == (1, 4, bytes.fromhex("00000002")):
                    response = frame_with_crc(bytes.fromhex("01040443668000"))
                elif unit == 2 and function == 1:
                    response = frame_with_crc(bytes([2, 1, 1, int(self.relay_on)]))
                elif unit == 2 and function == 5:
                    self.relay_on = request[4:6] == bytes.fromhex("ff00")
                    response = request
                else:
                    response = frame_with_crc(bytes([unit, function | 0x80, 2]))
                if self.bad_crc_once:
                    self.bad_crc_once = False
                    response = response[:-1] + bytes([response[-1] ^ 0xFF])
                os.write(self.master_fd, response)

    def stop(self) -> None:
        self._stopped = True


@pytest.mark.anyio
async def test_two_http_services_with_real_pty_and_restart_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        parent_command_routes.automations,
        "idempotency_store",
        SQLiteAutomationIdempotencyStore(tmp_path / "automation-actions.sqlite3"),
    )
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    slave_name = os.ttyname(slave_fd)
    simulator = RTUDeviceSimulator(master_fd)
    simulator_task = asyncio.create_task(simulator.run())
    sidecar_port, parent_port = free_port(), free_port()
    token = "e2e-internal-token"
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", token)
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_URL", f"http://127.0.0.1:{sidecar_port}")
    sidecar_server, sidecar_task = await start_server(sidecar_app, sidecar_port)
    parent_server, parent_task = await start_server(parent_app, parent_port)
    headers = {"Authorization": f"Bearer {token}"}
    config = {
        "id": "e2e-bus",
        "host": "modbus-rtu-sidecar",
        "transport": "rtu_sidecar",
        "serial_port": slave_name,
        "profile_id": "e2e.realistic-devices",
        "profile_version": "1.0.0",
        "profile_provenance": "Eastron SDM630 and Waveshare official protocol fixtures",
        "poll_interval_seconds": 5,
        "points": [
            {
                "id": "phase_1_voltage",
                "name": "Phase 1 Voltage",
                "unit_id": 1,
                "area": "input_register",
                "address": 0,
                "data_type": "float32",
                "unit": "V"
            },
            {
                "id": "relay_1",
                "name": "Relay 1",
                "unit_id": 2,
                "area": "coil",
                "address": 0,
                "data_type": "bool",
                "writable": True
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            configured = await client.post(f"http://127.0.0.1:{parent_port}/config", json=config)
            assert configured.status_code == 200, configured.text
            entities = (await client.get(f"http://127.0.0.1:{parent_port}/entities")).json()["entities"]
            voltage = next(item for item in entities if item["id"] == "e2e-bus:phase_1_voltage")
            relay = next(item for item in entities if item["id"] == "e2e-bus:relay_1")
            assert voltage["state"]["point_value"] == pytest.approx(230.5)
            assert voltage["state"]["unit"] == "V"
            assert relay["entity_type"] == "switch"
            assert relay["state"]["point_value"] is False

            write = await client.post(
                f"http://127.0.0.1:{parent_port}/command",
                headers={"X-PiPhi-Idempotency-Key": f"e2e-relay-on-{uuid4()}"},
                json={
                    "command": "set_value",
                    "target": {"config_id": "e2e-bus", "device_id": "e2e-bus:relay_1"},
                    "params": {"value": True},
                    "capability": "action.set_value"
                },
            )
            assert write.status_code == 200, write.text
            assert write.json()["status"] == "success", write.text
            assert simulator.relay_on is True, write.text

            simulator.bad_crc_once = True
            degraded = await client.post(
                f"http://127.0.0.1:{sidecar_port}/v1/modbus/refresh",
                headers=headers,
                json={"config_id": "e2e-bus", "point_id": "phase_1_voltage"},
            )
            assert degraded.status_code == 200
            degraded_point = next(
                point for point in degraded.json()["points"] if point["id"] == "phase_1_voltage"
            )
            assert degraded_point["quality"] == "unavailable"
            recovered = await client.post(
                f"http://127.0.0.1:{sidecar_port}/v1/modbus/refresh",
                headers=headers,
                json={"config_id": "e2e-bus", "point_id": "phase_1_voltage"},
            )
            assert next(
                point for point in recovered.json()["points"] if point["id"] == "phase_1_voltage"
            )["quality"] == "good"

            await stop_server(sidecar_server, sidecar_task)
            sidecar_server, sidecar_task = await start_server(sidecar_app, sidecar_port)
            refreshed = await client.get(
                f"http://127.0.0.1:{parent_port}/state?refresh=true&refresh_request_id={uuid4()}"
            )
            assert refreshed.status_code == 200, refreshed.text
            snapshot = refreshed.json()["entries"]["e2e-bus"]["latest_state"]
            assert snapshot["connected"] is True
            assert snapshot["profile_id"] == "e2e.realistic-devices"
            assert slave_name not in str(refreshed.json())
    finally:
        if not sidecar_task.done():
            await stop_server(sidecar_server, sidecar_task)
        await stop_server(parent_server, parent_task)
        simulator.stop()
        os.close(master_fd)
        os.close(slave_fd)
        simulator_task.cancel()
        await asyncio.gather(simulator_task, return_exceptions=True)
