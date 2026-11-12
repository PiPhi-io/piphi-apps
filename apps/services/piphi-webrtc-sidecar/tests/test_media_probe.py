from __future__ import annotations

import json
from pathlib import Path

from piphi_webrtc_sidecar.media_probe import CameraVideoProbe, parse_ffprobe_video


def test_probe_classifies_constrained_baseline_as_browser_safe() -> None:
    probe = parse_ffprobe_video(
        {
            "streams": [
                {
                    "codec_name": "h264",
                    "profile": "Constrained Baseline",
                    "level": 41,
                    "pix_fmt": "yuv420p",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                }
            ]
        }
    )

    assert probe is not None
    assert probe.browser_safe_h264 is True
    assert probe.frames_per_second == 30


def test_probe_requires_transcode_for_main_high_hevc_and_unknown_video() -> None:
    variants = [
        CameraVideoProbe("h264", "main", 40, "yuv420p", 1920, 1080, 20),
        CameraVideoProbe("h264", "high", 42, "yuv420p", 3840, 2160, 30),
        CameraVideoProbe("hevc", "main", 40, "yuv420p", 1920, 1080, 20),
        CameraVideoProbe("mjpeg", "", None, "yuvj420p", 1280, 720, 15),
        CameraVideoProbe("h264", "baseline", 51, "yuv420p", 1920, 1080, 30),
    ]

    assert all(probe.browser_safe_h264 is False for probe in variants)


def test_compatibility_catalog_accounts_for_every_strategy() -> None:
    catalog_path = Path(__file__).parents[1] / "docs" / "camera-compatibility.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = payload["strategies"]

    assert payload["contract"] == "camera.media.compatibility.v1"
    assert {row["status"] for row in rows} == {"implemented", "planned"}
    assert all(row.get("reason") for row in rows if row["status"] == "planned")
    implemented = {row["input"] for row in rows if row["status"] == "implemented"}
    assert implemented == {
        "h264-baseline-or-constrained-baseline",
        "h264-main-or-high",
        "hevc",
        "mjpeg-or-other-video",
        "probe-failed-or-unknown",
    }
