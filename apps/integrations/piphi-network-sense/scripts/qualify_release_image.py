#!/usr/bin/env python3
"""Qualify an exact Sense image with a deterministic, network-isolated account."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from piphi_runtime_kit_python import build_runtime_auth_headers

CONFIG_ID = "sense-release-qualification"
CONTAINER_ID = "sense-release-container"
INTERNAL_TOKEN = "sense-release-runtime-token"
SCENARIO = "release-qualification-v1"


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def inspect_image(
    image: str,
    *,
    version: str,
    revision: str,
    manifest_sha256: str,
    behaviors_sha256: str,
) -> None:
    if "@sha256:" in image:
        run("docker", "pull", image)
    inspected = json.loads(run("docker", "image", "inspect", image).stdout)[0]
    config = inspected.get("Config") or {}
    labels = config.get("Labels") or {}
    expected = {
        "org.opencontainers.image.version": version,
        "org.opencontainers.image.revision": revision,
        "io.piphi.manifest.sha256": manifest_sha256,
        "io.piphi.behaviors.sha256": behaviors_sha256,
    }
    if config.get("User") != "piphi":
        raise AssertionError(f"image user is {config.get('User')!r}, expected 'piphi'")
    if "/var/lib/piphi" not in (config.get("Volumes") or {}):
        raise AssertionError("image does not declare /var/lib/piphi persistence")
    for key, value in expected.items():
        if labels.get(key) != value:
            raise AssertionError(f"image label {key}={labels.get(key)!r}, expected {value!r}")


_REQUEST_SCRIPT = r"""
import base64,json,sys
from urllib.error import HTTPError
from urllib.request import Request,urlopen
method,url,headers64,payload64,expected=sys.argv[1:]
headers=json.loads(base64.b64decode(headers64))
payload=None if not payload64 else base64.b64decode(payload64)
request=Request(url,data=payload,headers=headers,method=method)
try:
    response=urlopen(request,timeout=5); status=response.status; body=response.read()
except HTTPError as exc:
    status=exc.code; body=exc.read()
if status != int(expected):
    raise SystemExit(f"status={status} expected={expected} body={body.decode(errors='replace')}")
print(body.decode() or '{}')
"""


def request_json(
    container: str,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    request_headers = {"Accept": "application/json", **(headers or {})}
    body = b"" if payload is None else json.dumps(payload).encode()
    if body:
        request_headers["Content-Type"] = "application/json"
    completed = run(
        "docker", "exec", container, "python", "-c", _REQUEST_SCRIPT,
        method,
        f"http://127.0.0.1:8090{path}",
        base64.b64encode(json.dumps(request_headers).encode()).decode(),
        base64.b64encode(body).decode(),
        str(expected_status),
    )
    parsed = json.loads(completed.stdout or "{}")
    if not isinstance(parsed, dict):
        raise AssertionError(f"{path} did not return a JSON object")
    return parsed


def start_container(image: str, name: str, volume: str) -> None:
    run(
        "docker", "run", "--detach", "--name", name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--volume", f"{volume}:/var/lib/piphi",
        "--env", f"PIPHI_INTEGRATION_INTERNAL_TOKEN={INTERNAL_TOKEN}",
        "--env", f"PIPHI_SENSE_FAKE_ACCOUNT={SCENARIO}",
        image,
    )


def wait_for_health(container: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    error = "container did not start"
    while time.monotonic() < deadline:
        try:
            return request_json(container, "/health")
        except subprocess.CalledProcessError as exc:
            error = exc.stderr or exc.stdout
            time.sleep(0.25)
    logs = run("docker", "logs", container, check=False).stdout
    raise AssertionError(f"release image did not become healthy: {error}\n{logs}")


def stop_container(name: str) -> None:
    run("docker", "rm", "--force", name, check=False)


def configure(container: str, headers: dict[str, str]) -> None:
    result = request_json(
        container,
        "/config",
        method="POST",
        headers=headers,
        payload={
            "id": CONFIG_ID,
            "container_id": CONTAINER_ID,
            "integration_id": "piphi-network-sense",
            "email": "fixture@example.invalid",
            "password": "fixture-password",
            "alias": "Qualification account",
            "poll_interval_seconds": 3600,
            "trend_interval_seconds": 3600,
            "expose_appliance_activity": True,
            "expose_timeline": True,
        },
    )
    if result.get("config_id") != CONFIG_ID:
        raise AssertionError(f"configuration identity drifted: {result}")


def assert_runtime(container: str, headers: dict[str, str], *, version: str) -> None:
    protected = [
        "/diagnostics", "/discover", "/ui-config", "/contract", "/entities",
        "/state", "/events", "/openapi.json", "/docs",
    ]
    for path in protected:
        request_json(container, path, expected_status=401)
    contract = request_json(container, "/contract", headers=headers)
    if contract.get("version") != version:
        raise AssertionError(f"contract version mismatch: {contract}")
    configure(container, headers)
    state = request_json(container, "/state", headers=headers)
    rendered = json.dumps(state, sort_keys=True)
    for secret in ("fixture@example.invalid", "fixture-password", INTERNAL_TOKEN):
        if secret in rendered:
            raise AssertionError("state exposed qualification credentials")
    snapshot = ((state.get("entries") or {}).get(CONFIG_ID) or {}).get("latest_state") or {}
    if snapshot.get("active_power_w") != 842.5:
        raise AssertionError(f"fake-account state was not projected: {state}")
    if snapshot.get("freshness", {}).get("realtime", {}).get("stale") is not False:
        raise AssertionError(f"realtime freshness is incorrect: {snapshot.get('freshness')}")
    if snapshot.get("periods", {}).get("daily", {}).get("kind") != "provider_local_calendar_day":
        raise AssertionError(f"daily period semantics are missing: {snapshot.get('periods')}")
    entities = request_json(container, "/entities", headers=headers).get("entities") or []
    monitor_ids = [item.get("device_id") for item in entities if item.get("entity_type") == "energy_monitor"]
    if monitor_ids != ["qualification-monitor-01"]:
        raise AssertionError(f"provider identity was not stable: {entities}")
    diagnostics = request_json(container, "/diagnostics", headers=headers)
    if any(secret in json.dumps(diagnostics) for secret in ("fixture@example.invalid", "fixture-password")):
        raise AssertionError("diagnostics exposed account credentials")


def qualify(args: argparse.Namespace) -> dict[str, Any]:
    inspect_image(
        args.image,
        version=args.version,
        revision=args.revision,
        manifest_sha256=args.manifest_sha256,
        behaviors_sha256=args.behaviors_sha256,
    )
    suffix = f"{os.getpid()}-{int(time.time())}"
    container = f"piphi-sense-qualification-{suffix}"
    volume = f"piphi-sense-data-{suffix}"
    headers = dict(build_runtime_auth_headers(container_id=CONTAINER_ID, internal_token=INTERNAL_TOKEN))
    run("docker", "volume", "create", volume)
    try:
        start_container(args.image, container, volume)
        wait_for_health(container)
        assert_runtime(container, headers, version=args.version)
        stop_container(container)
        start_container(args.image, container, volume)
        wait_for_health(container)
        # Core-managed configuration is re-submitted after restart; the exact
        # account/device identity must be restored rather than regenerated.
        assert_runtime(container, headers, version=args.version)
        return {
            "status": "passed",
            "image": args.image,
            "version": args.version,
            "network": "none",
            "read_only_rootfs": True,
            "fake_account": SCENARIO,
            "restart_identity_restored": True,
            "live_account_qualification": False,
        }
    finally:
        stop_container(container)
        run("docker", "volume", "rm", "--force", volume, check=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--behaviors-sha256", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(qualify(parse_args()), sort_keys=True))
