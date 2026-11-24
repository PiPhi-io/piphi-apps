from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from piphi_network_tp_link.lib.kasa_client import fetch_device_state
from piphi_network_tp_link.lib.security import redact

READ_ONLY_COMMANDS = frozenset({"read_energy", "refresh"})
SAFE_VERSION_KEYS = (
    "fw_ver",
    "firmware_version",
    "hw_ver",
    "hw_version",
    "sw_ver",
)


def load_local_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            parsed = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(f"invalid qualification environment line: {raw_line!r}") from exc
        if len(parsed) != 1 or "=" not in parsed[0]:
            raise ValueError(f"invalid qualification environment line: {raw_line!r}")
        key, value = parsed[0].split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _fingerprint(snapshot: dict[str, Any]) -> str:
    identity = str(snapshot.get("mac") or snapshot.get("device_id") or "").strip()
    if not identity:
        raise ValueError("device did not provide a stable physical identity")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _safe_feature(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        key: redact(feature.get(key))
        for key in ("id", "type", "category", "unit", "choices", "range", "writable")
        if feature.get(key) is not None
    }


def sanitize_qualification_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    sys_info = snapshot.get("sys_info") if isinstance(snapshot.get("sys_info"), dict) else {}
    commands = {
        str(command.get("id"))
        for command in snapshot.get("supported_commands", [])
        if isinstance(command, dict) and command.get("id")
    }
    if not commands <= READ_ONLY_COMMANDS:
        raise ValueError("device snapshot advertised an unqualified write command")
    features = snapshot.get("features") if isinstance(snapshot.get("features"), dict) else {}
    children = snapshot.get("children") if isinstance(snapshot.get("children"), list) else []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_commands = {
            str(command.get("id"))
            for command in child.get("supported_commands", [])
            if isinstance(command, dict) and command.get("id")
        }
        if not child_commands <= READ_ONLY_COMMANDS:
            raise ValueError("child snapshot advertised an unqualified write command")
    return {
        "identity_fingerprint": _fingerprint(snapshot),
        "model": snapshot.get("model"),
        "device_type": snapshot.get("device_type"),
        "versions": {
            key: sys_info[key]
            for key in SAFE_VERSION_KEYS
            if key in sys_info and isinstance(sys_info[key], (str, int, float))
        },
        "capabilities": sorted(str(item) for item in snapshot.get("capabilities", [])),
        "features": sorted(
            (_safe_feature(feature) for feature in features.values() if isinstance(feature, dict)),
            key=lambda feature: str(feature.get("id", "")),
        ),
        "energy_metrics_present": sorted(
            str(key)
            for key in (snapshot.get("energy") or {})
            if key in {"current_power_w", "month_kwh", "today_kwh"}
        ),
        "supported_commands": sorted(commands),
        "children": [
            {
                "model": child.get("model"),
                "capabilities": sorted(str(item) for item in child.get("capabilities", [])),
                "supported_commands": sorted(
                    str(command.get("id"))
                    for command in child.get("supported_commands", [])
                    if isinstance(command, dict) and command.get("id") in READ_ONLY_COMMANDS
                ),
            }
            for child in children
            if isinstance(child, dict)
        ],
    }


async def qualify_read_only(
    *,
    host: str,
    username: str | None,
    password: str | None,
    samples: int = 3,
    fetcher: Callable[..., Awaitable[dict[str, Any]]] = fetch_device_state,
) -> dict[str, Any]:
    if not 2 <= samples <= 10:
        raise ValueError("samples must be between 2 and 10")
    observations: list[dict[str, Any]] = []
    latencies: list[int] = []
    for _ in range(samples):
        started = time.monotonic()
        snapshot = await fetcher(host=host, username=username, password=password)
        latencies.append(round((time.monotonic() - started) * 1000))
        observations.append(sanitize_qualification_snapshot(snapshot))
    fingerprints = {item["identity_fingerprint"] for item in observations}
    if len(fingerprints) != 1:
        raise ValueError("device identity changed between read-only samples")
    capability_sets = {tuple(item["capabilities"]) for item in observations}
    if len(capability_sets) != 1:
        raise ValueError("negotiated capabilities changed between read-only samples")
    qualification_profiles = {
        json.dumps(
            {key: value for key, value in item.items() if key != "identity_fingerprint"},
            sort_keys=True,
        )
        for item in observations
    }
    if len(qualification_profiles) != 1:
        raise ValueError("device qualification profile changed between read-only samples")
    return {
        "schema_version": 1,
        "mode": "read_only",
        "captured_at": datetime.now(UTC).isoformat(),
        "python_kasa_version": version("python-kasa"),
        "sample_count": samples,
        "latency_ms": {"min": min(latencies), "max": max(latencies)},
        "device": observations[-1],
        "qualification": {
            "connectivity": "observed",
            "identity_stability": "observed",
            "capability_stability": "observed",
            "telemetry_accuracy": "not_verified",
            "writes": "not_exercised",
        },
    }


def write_private_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.write_text(encoded, encoding="utf-8")
    os.chmod(path, 0o600)
