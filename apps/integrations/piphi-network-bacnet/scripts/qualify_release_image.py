#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = ROOT / "tests" / "fixtures" / "senseedge_simulator.py"
BASE_URL = "http://127.0.0.1:4224"
QUALIFICATION_TOKEN = "bacnet-release-qualification-token"


def request_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if path != "/health":
        headers["X-PiPhi-Integration-Token"] = QUALIFICATION_TOKEN
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def wait_for_http(path: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return request_json(path)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"runtime did not become ready: {last_error}")


def wait_for_simulator(process: subprocess.Popen[str], timeout: float) -> None:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        raise RuntimeError("SenseEdge simulator did not become ready")
    line = process.stdout.readline().strip()
    if line != "senseedge_simulator=ready":
        stderr = process.stderr.read() if process.poll() is not None and process.stderr else ""
        raise RuntimeError(f"SenseEdge simulator failed: {line} {stderr}".strip())


def find_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("profile") == "kaiterra_sensedge_mini" and "device" in payload:
        return payload
    for value in payload.values():
        if isinstance(value, dict):
            match = find_snapshot(value)
            if match is not None:
                return match
    return None


def qualify(image: str, timeout: float) -> None:
    container = f"piphi-bacnet-qualification-{uuid.uuid4().hex[:12]}"
    image_user = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Config.User}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if image_user in {"", "0", "root", "0:0"}:
        raise AssertionError(f"release image must run as non-root, got {image_user!r}")
    simulator = subprocess.Popen(
        [sys.executable, str(SIMULATOR)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started_container = False
    try:
        wait_for_simulator(simulator, timeout)
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--network",
                "host",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/app/data:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=0700",
                "--env",
                f"PIPHI_INTEGRATION_INTERNAL_TOKEN={QUALIFICATION_TOKEN}",
                image,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        started_container = True
        health = wait_for_http("/health", timeout)
        if health.get("status") != "ok" and health.get("ok") is not True:
            raise AssertionError(f"unexpected health response: {health}")

        config = {
            "id": "release-qualification",
            "host": "127.0.0.2",
            "port": 47809,
            "device_instance": 1234,
            "local_address": "127.0.0.1/8",
            "local_device_instance": 4194000,
            "profile": "kaiterra_sensedge_mini",
            "poll_interval_seconds": 30,
        }
        configured = request_json("/config", config)
        if configured.get("status") != "configured":
            raise AssertionError(f"configuration was not accepted: {configured}")

        deadline = time.monotonic() + timeout
        snapshot = None
        while time.monotonic() < deadline:
            snapshot = find_snapshot(request_json("/state"))
            if snapshot is not None and snapshot.get("connected") is True:
                break
            time.sleep(0.2)
        if snapshot is None or snapshot.get("connected") is not True:
            raise AssertionError("the exact image did not read the simulated SenseEdge")

        device = snapshot["device"]
        metrics = snapshot["metrics"]
        assert device["device_instance"] == 1234
        assert device["vendor_id"] == 1307
        assert device["model_name"] == "Sensedge Mini SE-200"
        assert device["protocol_revision"] == 14
        assert metrics["connected"] is True
        assert metrics["pm2_5_ug_m3"] == 12.5
        assert metrics["temperature_c"] == 22.0

        entities = request_json("/entities")["entities"]
        assert len(entities) == 1
        assert entities[0]["capabilities"] == [
            "connected",
            "pm2_5_ug_m3",
            "temperature_c",
            "refresh",
        ]
        print(f"release_image_qualification=passed image={image}")
    except Exception:
        if started_container:
            subprocess.run(["docker", "logs", container], check=False)
        raise
    finally:
        if started_container:
            subprocess.run(
                ["docker", "rm", "--force", container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        simulator.terminate()
        try:
            simulator.wait(timeout=5)
        except subprocess.TimeoutExpired:
            simulator.kill()
            simulator.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Qualify an exact BACnet integration image against a real BACpypes UDP simulator."
    )
    parser.add_argument("--image", required=True, help="Exact local tag or immutable image digest")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    qualify(args.image, args.timeout)


if __name__ == "__main__":
    main()
