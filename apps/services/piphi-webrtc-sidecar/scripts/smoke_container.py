#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

TOKEN = "piphi-container-smoke-token"
ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Docker error"
        raise RuntimeError(f"docker {args[0]} failed: {detail}")
    return result.stdout.strip()


def request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout: float = 3,
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = urllib.request.Request(url, headers=headers, data=data, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected an object response from {url}")
    return payload


def request_bytes(url: str, *, token: str, timeout: float = 10) -> tuple[str, bytes]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.headers.get_content_type(), response.read()


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
    script = r"""
import json
import urllib.parse
import urllib.request

base = "http://127.0.0.1:1984/api/streams"
names = ("ha_fixture_a", "ha_fixture_b")
source = "ffmpeg:virtual?video=testsrc2&size=640x360#video=h264"

def streams():
    with urllib.request.urlopen(base, timeout=5) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError("go2rtc returned an invalid stream inventory")
    return payload

for name in names:
    query = urllib.parse.urlencode({"name": name, "src": source})
    request = urllib.request.Request(base + "?" + query, method="PUT")
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status not in (200, 201, 204):
            raise RuntimeError(f"stream setup returned {response.status}")

created = streams()
if not all(name in created for name in names):
    raise RuntimeError("go2rtc did not retain both fixture streams")
with urllib.request.urlopen(
    "http://127.0.0.1:1984/api/frame.jpeg?src=ha_fixture_a",
    timeout=20,
) as response:
    image = response.read()
if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
    raise RuntimeError("go2rtc did not return a complete JPEG fixture frame")

first_delete = urllib.request.Request(
    base + "?" + urllib.parse.urlencode({"src": names[0]}), method="DELETE"
)
with urllib.request.urlopen(first_delete, timeout=5):
    pass
after_first = streams()
if names[0] in after_first or names[1] not in after_first:
    raise RuntimeError("go2rtc pairwise cleanup removed the wrong streams")

second_delete = urllib.request.Request(
    base + "?" + urllib.parse.urlencode({"src": names[1]}), method="DELETE"
)
with urllib.request.urlopen(second_delete, timeout=5):
    pass
after_second = streams()
if any(name in after_second for name in names):
    raise RuntimeError("go2rtc fixture cleanup left a stream behind")

print(json.dumps({
    "jpeg_bytes": len(image),
    "content_type": "image/jpeg",
    "pairwise_cleanup": True,
}))
"""
    return json.loads(docker("exec", container, "python", "-c", script))


def verify_secret_failure_redaction(base_url: str, container: str) -> dict[str, object]:
    secret = f"smoke-secret-{uuid4().hex}"
    payload: dict[str, object] = {
        "contract_version": "camera.media.v1",
        "message_type": "camera.sidecar.session.open",
        "audience": "core-sidecar",
        "source": {
            "contract_version": "camera.media.v1",
            "message_type": "camera.source",
            "audience": "core-sidecar",
            "camera_id": "container-smoke-unreachable",
            "source_url": f"rtsp://smoke:{secret}@192.0.2.1:554/live",
            "source_protocol": "rtsp",
            "preferred_transport": "tcp",
            "connect_timeout_seconds": 1,
        },
        "offer": {"type": "offer", "sdp": "v=0"},
        "idle_timeout_seconds": 10,
    }
    try:
        request_json(
            f"{base_url}/v1/camera-media/sessions",
            token=TOKEN,
            method="POST",
            payload=payload,
            timeout=15,
        )
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        if exc.code != 502:
            raise RuntimeError(f"secret-bearing failure returned {exc.code}") from exc
    else:
        raise RuntimeError("unreachable secret-bearing source unexpectedly opened")
    logs = docker("logs", container)
    if secret in response_body or secret in logs:
        raise RuntimeError("camera source secret appeared in failure evidence")
    return {"status": 502, "secret_redacted": True}


def verify_analysis_media(base_url: str, container: str) -> dict[str, object]:
    stream_name = "analysis_fixture"
    setup_script = f'''\
import urllib.parse, urllib.request
query = urllib.parse.urlencode({{
    "name": "{stream_name}",
    "src": "ffmpeg:virtual?video=testsrc2&size=320x180#video=h264",
}})
request = urllib.request.Request("http://127.0.0.1:1984/api/streams?" + query, method="PUT")
urllib.request.urlopen(request, timeout=5).read()
'''
    cleanup_script = f'''\
import urllib.parse, urllib.request
query = urllib.parse.urlencode({{"src": "{stream_name}"}})
request = urllib.request.Request("http://127.0.0.1:1984/api/streams?" + query, method="DELETE")
urllib.request.urlopen(request, timeout=5).read()
'''
    docker("exec", container, "python", "-c", setup_script)
    try:
        issued = request_json(
            f"{base_url}/v1/analysis-media",
            token=TOKEN,
            method="POST",
            payload={
                "source": {
                    "camera_id": "synthetic-container-fixture",
                    "source_url": f"rtsp://127.0.0.1:8554/{stream_name}",
                    "source_protocol": "rtsp",
                },
                "ttl_seconds": 30,
            },
            timeout=20,
        )
        media_ref = issued.get("media_ref")
        if not isinstance(media_ref, str) or not media_ref:
            raise RuntimeError("analysis-media issuance did not return an opaque reference")
        content_type, image = request_bytes(
            f"{base_url}/v1/analysis-media/{media_ref}", token=TOKEN
        )
        if content_type != "image/jpeg" or not image.startswith(b"\xff\xd8"):
            raise RuntimeError("analysis-media retrieval did not return a JPEG fixture")
        try:
            request_bytes(f"{base_url}/v1/analysis-media/{media_ref}", token=TOKEN)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        else:
            raise RuntimeError("analysis-media reference was replayable")
        logs = docker("logs", container)
        if media_ref in logs:
            raise RuntimeError("analysis-media reference appeared in container logs")
        streams = json.loads(
            docker(
                "exec",
                container,
                "python",
                "-c",
                "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:1984/api/streams'))))",
            )
        )
        if any(str(name).startswith("piphi_analysis_") for name in streams):
            raise RuntimeError("analysis-media capture left a temporary stream behind")
        return {
            "content_type": content_type,
            "jpeg_bytes": len(image),
            "reference_redacted": True,
            "replay_rejected": True,
        }
    finally:
        docker("exec", container, "python", "-c", cleanup_script)


def smoke(image: str) -> dict[str, object]:
    container = f"piphi-webrtc-smoke-{uuid4().hex[:12]}"
    try:
        docker(
            "run",
            "--detach",
            "--name",
            container,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "10001:10001",
            "--env",
            f"PIPHI_SIDECAR_TOKEN={TOKEN}",
            "--publish",
            "127.0.0.1::8090",
            image,
        )
        binding = docker("port", container, "8090/tcp")
        base_url = f"http://{binding}"
        health = wait_for_health(base_url)
        if health.get("go2rtc_version") != "1.9.15":
            raise RuntimeError("container did not run the pinned go2rtc 1.9.15 build")
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
        analysis_media = verify_analysis_media(base_url, container)
        failure = verify_secret_failure_redaction(base_url, container)
        return {
            "image": image,
            "health": health,
            "status": status,
            "media": media,
            "analysis_media": analysis_media,
            "failure": failure,
        }
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
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the exact package image before running the smoke test",
    )
    args = parser.parse_args()
    if args.build:
        subprocess.run(
            ["docker", "build", "--pull=false", "--tag", args.image, str(ROOT)],
            check=True,
        )
    print(json.dumps(smoke(args.image), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
