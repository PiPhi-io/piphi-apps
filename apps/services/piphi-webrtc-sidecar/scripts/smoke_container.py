#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from uuid import uuid4

TOKEN = "piphi-container-smoke-token"


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def request_json(url: str, *, token: str | None = None) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected an object response from {url}")
    return payload


def wait_for_health(base_url: str) -> dict[str, object]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            health = request_json(f"{base_url}/health")
        except (OSError, ValueError):
            time.sleep(0.25)
            continue
        if health.get("status") == "healthy" and health.get("go2rtc_available") is True:
            return health
        time.sleep(0.25)
    raise RuntimeError("container did not report healthy go2rtc within 30 seconds")


def verify_media_fixture(container: str) -> dict[str, object]:
    script = """
import json
import urllib.parse
import urllib.request

source = "ffmpeg:virtual?video=testsrc2&size=640x360#video=h264"
query = urllib.parse.urlencode({"name": "ha_fixture", "src": source})
request = urllib.request.Request(
    "http://127.0.0.1:1984/api/streams?" + query,
    method="PUT",
)
with urllib.request.urlopen(request, timeout=5) as response:
    if response.status != 200:
        raise RuntimeError(f"stream setup returned {response.status}")
with urllib.request.urlopen(
    "http://127.0.0.1:1984/api/frame.jpeg?src=ha_fixture",
    timeout=20,
) as response:
    image = response.read()
if not image.startswith(b"\\xff\\xd8") or not image.endswith(b"\\xff\\xd9"):
    raise RuntimeError("go2rtc did not return a complete JPEG fixture frame")
print(json.dumps({"jpeg_bytes": len(image), "content_type": "image/jpeg"}))
"""
    return json.loads(docker("exec", container, "python", "-c", script))


def smoke(image: str) -> dict[str, object]:
    container = f"piphi-webrtc-smoke-{uuid4().hex[:12]}"
    try:
        docker(
            "run",
            "--detach",
            "--name",
            container,
            "--env",
            f"PIPHI_SIDECAR_TOKEN={TOKEN}",
            "--publish",
            "127.0.0.1::8090",
            image,
        )
        binding = docker("port", container, "8090/tcp")
        base_url = f"http://{binding}"
        health = wait_for_health(base_url)
        try:
            request_json(f"{base_url}/v1/camera-media/status")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
        else:
            raise RuntimeError("media status accepted an unauthenticated request")
        status = request_json(f"{base_url}/v1/camera-media/status", token=TOKEN)
        if status.get("ready") is not True:
            raise RuntimeError("authenticated media status is not ready")
        media = verify_media_fixture(container)
        return {"image": image, "health": health, "status": status, "media": media}
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            check=False,
            capture_output=True,
            text=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the packaged go2rtc media service")
    parser.add_argument("--image", default="piphi-webrtc-sidecar:ha-baseline")
    args = parser.parse_args()
    print(json.dumps(smoke(args.image), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
