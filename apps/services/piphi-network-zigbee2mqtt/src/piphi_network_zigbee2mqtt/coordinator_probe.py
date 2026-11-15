from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from urllib.parse import urlsplit

from .bridge_models import CoordinatorProbeResponse


def probe_coordinator(
    port: str,
    *,
    proc_root: Path = Path("/proc"),
    system: str | None = None,
) -> CoordinatorProbeResponse:
    token = str(port or "").strip()
    if not token:
        raise ValueError("Coordinator port is required.")
    if "://" in token:
        return _probe_network_coordinator(token)
    selected_system = (system or platform.system()).lower()
    if selected_system == "linux":
        return _probe_linux_serial(token, proc_root)
    return _probe_serial_open(token)


def _probe_linux_serial(port: str, proc_root: Path) -> CoordinatorProbeResponse:
    target = Path(port).expanduser().resolve()
    if not target.exists():
        return CoordinatorProbeResponse(
            available=False,
            in_use=False,
            method="linux_proc_fds",
            exclusive_verified=True,
            message="Coordinator device does not exist.",
        )
    holders: list[str] = []
    own_pid = str(os.getpid())
    for process_dir in proc_root.iterdir():
        if not process_dir.name.isdigit() or process_dir.name == own_pid:
            continue
        fd_dir = process_dir / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for descriptor in descriptors:
            try:
                if descriptor.resolve() == target:
                    holders.append(_process_label(process_dir))
                    break
            except (FileNotFoundError, PermissionError, OSError):
                continue
    holders = sorted(set(holders))
    return CoordinatorProbeResponse(
        available=not holders,
        in_use=bool(holders),
        method="linux_proc_fds",
        exclusive_verified=True,
        holders=holders,
        message="Coordinator is already open by another process." if holders else None,
    )


def _probe_serial_open(port: str) -> CoordinatorProbeResponse:
    try:
        import serial

        handle = serial.Serial(port=port, timeout=0, write_timeout=0, exclusive=True)
        handle.close()
    except (OSError, serial.SerialException) as exc:
        return CoordinatorProbeResponse(
            available=False,
            in_use=True,
            method="exclusive_serial_open",
            exclusive_verified=True,
            message=f"Coordinator could not be opened exclusively: {type(exc).__name__}.",
        )
    return CoordinatorProbeResponse(
        available=True,
        in_use=False,
        method="exclusive_serial_open",
        exclusive_verified=True,
    )


def _probe_network_coordinator(port: str) -> CoordinatorProbeResponse:
    parsed = urlsplit(port)
    if parsed.scheme not in {"tcp", "socket"} or not parsed.hostname or not parsed.port:
        raise ValueError("Network coordinator port must be tcp:// or socket:// with an explicit port.")
    try:
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2.0):
            pass
    except OSError as exc:
        return CoordinatorProbeResponse(
            available=False,
            in_use=False,
            method="tcp_reachability",
            exclusive_verified=False,
            message=f"Network coordinator is unreachable: {type(exc).__name__}.",
        )
    return CoordinatorProbeResponse(
        available=True,
        in_use=False,
        method="tcp_reachability",
        exclusive_verified=False,
        message="TCP reachability verified; remote exclusivity cannot be probed.",
    )


def _process_label(process_dir: Path) -> str:
    try:
        command = (process_dir / "comm").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, OSError):
        command = "unknown"
    return f"pid:{process_dir.name}:{command[:64]}"
