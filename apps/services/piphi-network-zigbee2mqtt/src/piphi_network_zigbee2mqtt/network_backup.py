from __future__ import annotations

import os
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .bridge_models import NetworkBackupResponse

NETWORK_FILES = (
    "configuration.yaml",
    "coordinator_backup.json",
    "database.db",
    "state.json",
)


def create_network_backup(data_path: str) -> NetworkBackupResponse:
    root = _approved_data_root(data_path)
    available = [name for name in NETWORK_FILES if _safe_network_file(root, name)]
    if "configuration.yaml" not in available:
        raise ValueError("A Zigbee2MQTT configuration.yaml is required before backup.")
    backup_dir = root / "backups"
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"zigbee-network-{timestamp}.zip"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(descriptor, "wb") as handle,
        zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive,
    ):
        for name in available:
            archive.write(root / name, arcname=name)
    os.chmod(target, 0o600)
    digest = file_digest(target)
    return NetworkBackupResponse(
        backup_path=str(target),
        backup_sha256=digest,
        files=available,
    )


def verify_network_backup(backup_path: str | None, expected_sha256: str | None) -> None:
    if not backup_path or not expected_sha256:
        raise ValueError("Changing Zigbee network identity requires verified backup evidence.")
    target = Path(backup_path).expanduser().resolve()
    root = _approved_data_root(str(target.parent.parent))
    if target.parent != root / "backups" or not target.is_file():
        raise ValueError("Backup evidence must reference a managed Zigbee2MQTT backup.")
    if file_digest(target) != expected_sha256:
        raise ValueError("Zigbee network backup checksum verification failed.")
    try:
        with zipfile.ZipFile(target) as archive:
            names = set(archive.namelist())
            if "configuration.yaml" not in names:
                raise ValueError("Zigbee network backup is missing configuration.yaml.")
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise ValueError("Zigbee network backup contains unsafe paths.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Zigbee network backup is invalid.") from exc


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _approved_data_root(data_path: str) -> Path:
    requested = Path(data_path).expanduser().resolve()
    configured = os.getenv(
        "PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS",
        f"/app/data{os.pathsep}/var/lib/piphi/zigbee2mqtt",
    )
    approved = {Path(value).expanduser().resolve() for value in configured.split(os.pathsep) if value}
    if requested not in approved:
        raise ValueError("Backup data_path must be an approved Zigbee2MQTT data root.")
    return requested


def _safe_network_file(root: Path, name: str) -> bool:
    candidate = root / name
    if not candidate.is_file():
        return False
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise ValueError(f"Zigbee2MQTT network file {name} cannot be a symlink.")
    return True
