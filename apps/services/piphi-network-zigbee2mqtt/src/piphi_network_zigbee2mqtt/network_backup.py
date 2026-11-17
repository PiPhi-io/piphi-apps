from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .bridge_models import (
    EncryptedBackupExportResponse,
    NetworkBackupResponse,
    NetworkRestoreResponse,
)
from .config_store import _write_private
from .settings import INTEGRATION_VERSION

BACKUP_METADATA = "piphi-backup.json"
EXCLUDED_TOP_LEVEL = {"backups", "coordinator-claims", "piphi-sidecar"}
ENCRYPTED_BACKUP_MAGIC = b"PIPHI-ZIGBEE-AES256-GCM-V1\n"
ESSENTIAL_NETWORK_FILES = {"configuration.yaml", "database.db"}
COORDINATOR_BACKUP_FILE = "coordinator_backup.json"
MAX_COORDINATOR_BACKUP_AGE_SECONDS = 300
COORDINATOR_BACKUP_SUPPORTED_FAMILIES = {"ember", "zstack"}


def create_network_backup(
    data_path: str,
    *,
    adapter_family: str = "unknown",
    adapter_backup_supported: bool = False,
    workload_fenced: bool = False,
    zigbee2mqtt_version: str = "2.14.3",
    now: datetime | None = None,
) -> NetworkBackupResponse:
    root = _approved_data_root(data_path)
    if not workload_fenced:
        raise ValueError("Zigbee2MQTT workload must be stopped and fenced before backup.")
    available = _network_files(root)
    missing = ESSENTIAL_NETWORK_FILES - set(available)
    if missing:
        raise ValueError(
            "Recoverable Zigbee backup is missing essential file(s): " + ", ".join(sorted(missing))
        )
    current = now or datetime.now(UTC)
    normalized_family = adapter_family.strip().lower()
    if normalized_family in {"", "unknown"}:
        raise ValueError("A known adapter family is required for recoverable backup evidence.")
    if not zigbee2mqtt_version.strip() or zigbee2mqtt_version.strip().lower() == "unknown":
        raise ValueError("Zigbee2MQTT version is required for recoverable backup evidence.")
    backup_supported = (
        adapter_backup_supported or normalized_family in COORDINATOR_BACKUP_SUPPORTED_FAMILIES
    )
    coordinator_created_at: str | None = None
    if backup_supported:
        coordinator = root / COORDINATOR_BACKUP_FILE
        if COORDINATOR_BACKUP_FILE not in available or not coordinator.is_file():
            raise ValueError("Adapter requires a fresh upstream coordinator backup.")
        modified = datetime.fromtimestamp(coordinator.stat().st_mtime, tz=UTC)
        age = (current - modified).total_seconds()
        if age < -5 or age > MAX_COORDINATOR_BACKUP_AGE_SECONDS:
            raise ValueError("Adapter requires a fresh upstream coordinator backup.")
        try:
            coordinator_payload = json.loads(coordinator.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Upstream coordinator backup is invalid.") from exc
        if not isinstance(coordinator_payload, dict):
            raise ValueError("Upstream coordinator backup is invalid.")
        coordinator_created_at = modified.isoformat()
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
        archive.writestr(
            BACKUP_METADATA,
            json.dumps(
                {
                    "format": 2,
                    "sidecar_version": INTEGRATION_VERSION,
                    "zigbee2mqtt_version": zigbee2mqtt_version,
                    "adapter_family": normalized_family,
                    "created_at": current.isoformat(),
                    "recoverable": True,
                    "workload_fenced": True,
                    "essential_files": sorted(ESSENTIAL_NETWORK_FILES),
                    "adapter_backup_supported": backup_supported,
                    "coordinator_backup_created_at": coordinator_created_at,
                },
                sort_keys=True,
            ),
        )
        for name in available:
            archive.write(root / name, arcname=name)
    os.chmod(target, 0o600)
    digest = file_digest(target)
    return NetworkBackupResponse(
        backup_path=str(target),
        backup_sha256=digest,
        files=available,
        adapter_family=normalized_family,
        zigbee2mqtt_version=zigbee2mqtt_version,
        coordinator_backup_created_at=coordinator_created_at,
        recoverable=True,
    )


def verify_network_backup(backup_path: str | None, expected_sha256: str | None) -> None:
    inspect_network_backup(backup_path, expected_sha256)


def inspect_network_backup(backup_path: str | None, expected_sha256: str | None) -> dict[str, object]:
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
            if BACKUP_METADATA not in names:
                raise ValueError("Zigbee network backup is missing compatibility metadata.")
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise ValueError("Zigbee network backup contains unsafe paths.")
            metadata = json.loads(archive.read(BACKUP_METADATA))
            if not isinstance(metadata, dict) or metadata.get("format") != 2:
                raise ValueError("Zigbee network backup metadata is unsupported.")
            backup_family = str(metadata.get("adapter_family") or "").strip().lower()
            zigbee2mqtt_version = str(metadata.get("zigbee2mqtt_version") or "").strip()
            if backup_family in {"", "unknown"} or zigbee2mqtt_version.lower() in {
                "",
                "unknown",
            }:
                raise ValueError("Zigbee network backup compatibility metadata is incomplete.")
            try:
                created_at = datetime.fromisoformat(str(metadata.get("created_at")))
            except ValueError as exc:
                raise ValueError("Zigbee network backup creation time is invalid.") from exc
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Zigbee network backup creation time is invalid.")
            missing = ESSENTIAL_NETWORK_FILES - names
            if missing:
                raise ValueError(
                    "Zigbee network backup is missing essential file(s): "
                    + ", ".join(sorted(missing))
                )
            if metadata.get("recoverable") is not True or metadata.get("workload_fenced") is not True:
                raise ValueError("Zigbee network backup lacks recoverability evidence.")
            requires_coordinator_backup = bool(metadata.get("adapter_backup_supported")) or (
                backup_family in COORDINATOR_BACKUP_SUPPORTED_FAMILIES
            )
            if requires_coordinator_backup and (
                COORDINATOR_BACKUP_FILE not in names
                or not metadata.get("coordinator_backup_created_at")
            ):
                raise ValueError("Zigbee network backup lacks coordinator recovery evidence.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Zigbee network backup is invalid.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Zigbee network backup metadata is invalid.") from exc
    return {**metadata, "files": sorted(names - {BACKUP_METADATA})}


def restore_network_backup(
    *,
    data_path: str,
    backup_path: str,
    expected_sha256: str,
    adapter_family: str,
    compatibility_evidence: str | None = None,
    rollback_adapter_family: str | None = None,
    workload_fenced: bool = False,
    post_restore_verify: Callable[[Path, dict[str, object]], bool | None] | None = None,
) -> NetworkRestoreResponse:
    root = _approved_data_root(data_path)
    if not workload_fenced:
        raise ValueError("Zigbee2MQTT workload must be stopped and fenced before restore.")
    metadata = inspect_network_backup(backup_path, expected_sha256)
    backup_family = str(metadata.get("adapter_family") or "unknown")
    if compatibility_evidence:
        raise ValueError("Free-form adapter compatibility evidence is not accepted.")
    if backup_family == "unknown" or backup_family != adapter_family.strip().lower():
        raise ValueError(
            f"Backup adapter family {backup_family!r} is not compatible with {adapter_family!r}."
        )
    rollback = create_network_backup(
        str(root),
        adapter_family=rollback_adapter_family or adapter_family,
        adapter_backup_supported=bool(metadata.get("adapter_backup_supported")),
        workload_fenced=True,
        zigbee2mqtt_version=str(metadata.get("zigbee2mqtt_version") or "unknown"),
    )
    staging = Path(mkdtemp(prefix=".restore-", dir=root))
    rollback_staging: Path | None = None
    try:
        _extract_backup(Path(backup_path), staging)
        restored_files = [str(item) for item in metadata["files"]]
        _replace_data_files(root, staging, restored_files)
        if post_restore_verify is not None and post_restore_verify(root, metadata) is False:
            raise ValueError("Zigbee post-restore verification failed.")
    except Exception:
        try:
            rollback_staging = Path(mkdtemp(prefix=".rollback-", dir=root))
            _extract_backup(Path(rollback.backup_path), rollback_staging)
            _replace_data_files(root, rollback_staging, rollback.files)
        finally:
            if rollback_staging is not None:
                shutil.rmtree(rollback_staging, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return NetworkRestoreResponse(
        restored=True,
        files=restored_files,
        rollback_backup=rollback,
        message="Zigbee2MQTT data restored; restart and post-restore verification are required.",
        verification_status="passed" if post_restore_verify is not None else "pending",
    )


def export_encrypted_backup(
    *,
    backup_path: str,
    expected_sha256: str,
    passphrase: str,
) -> EncryptedBackupExportResponse:
    inspect_network_backup(backup_path, expected_sha256)
    source = Path(backup_path).expanduser().resolve()
    root = _approved_data_root(str(source.parent.parent))
    export_dir = root / "exports"
    export_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(export_dir, 0o700)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_export_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), ENCRYPTED_BACKUP_MAGIC)
    target = export_dir / f"{source.stem}-{uuid4().hex}.piphi-zigbee-backup"
    _write_private(target, ENCRYPTED_BACKUP_MAGIC + salt + nonce + ciphertext)
    return EncryptedBackupExportResponse(
        export_path=str(target),
        export_sha256=file_digest(target),
    )


def import_encrypted_backup(
    *,
    data_path: str,
    export_path: str,
    expected_sha256: str,
    passphrase: str,
) -> NetworkBackupResponse:
    root = _approved_data_root(data_path)
    source = Path(export_path).expanduser().resolve()
    if source.parent != root / "exports" or not source.is_file():
        raise ValueError("Encrypted export must reference the managed Zigbee2MQTT export directory.")
    if file_digest(source) != expected_sha256:
        raise ValueError("Encrypted Zigbee backup checksum verification failed.")
    payload = source.read_bytes()
    minimum = len(ENCRYPTED_BACKUP_MAGIC) + 16 + 12 + 16
    if len(payload) < minimum or not payload.startswith(ENCRYPTED_BACKUP_MAGIC):
        raise ValueError("Encrypted Zigbee backup format is invalid.")
    offset = len(ENCRYPTED_BACKUP_MAGIC)
    salt = payload[offset : offset + 16]
    nonce = payload[offset + 16 : offset + 28]
    ciphertext = payload[offset + 28 :]
    try:
        plaintext = AESGCM(_derive_export_key(passphrase, salt)).decrypt(
            nonce,
            ciphertext,
            ENCRYPTED_BACKUP_MAGIC,
        )
    except InvalidTag as exc:
        raise ValueError("Encrypted Zigbee backup passphrase or authentication is invalid.") from exc
    backup_dir = root / "backups"
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = backup_dir / f"imported-{uuid4().hex}.zip"
    _write_private(target, plaintext)
    digest = file_digest(target)
    try:
        metadata = inspect_network_backup(str(target), digest)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return NetworkBackupResponse(
        backup_path=str(target),
        backup_sha256=digest,
        files=[str(name) for name in metadata["files"]],
        created_at=datetime.fromisoformat(str(metadata["created_at"])),
        adapter_family=str(metadata["adapter_family"]),
        zigbee2mqtt_version=str(metadata["zigbee2mqtt_version"]),
        coordinator_backup_created_at=(
            datetime.fromisoformat(str(metadata["coordinator_backup_created_at"]))
            if metadata.get("coordinator_backup_created_at")
            else None
        ),
        recoverable=True,
    )


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


def _derive_export_key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def _network_files(root: Path) -> list[str]:
    files: list[str] = []
    total_size = 0
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root)
        if not relative.parts or relative.parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        if relative.parts[0].startswith((".restore-", ".rollback-")):
            continue
        if candidate.is_symlink():
            raise ValueError(f"Zigbee2MQTT data file {relative} cannot be a symlink.")
        if not candidate.is_file():
            continue
        total_size += candidate.stat().st_size
        if total_size > 100 * 1024 * 1024 or len(files) >= 10_000:
            raise ValueError("Zigbee2MQTT data exceeds the bounded backup limit.")
        files.append(relative.as_posix())
    return files


def _extract_backup(backup: Path, staging: Path) -> None:
    with zipfile.ZipFile(backup) as archive:
        for member in archive.infolist():
            if member.filename == BACKUP_METADATA:
                continue
            relative = Path(member.filename)
            if member.is_dir() or relative.is_absolute() or ".." in relative.parts:
                if member.is_dir():
                    continue
                raise ValueError("Zigbee network backup contains unsafe paths.")
            target = staging / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write_private(target, archive.read(member))


def _replace_data_files(root: Path, staging: Path, restored_files: list[str]) -> None:
    desired = {Path(name) for name in restored_files}
    for current_name in reversed(_network_files(root)):
        current = Path(current_name)
        if current not in desired:
            (root / current).unlink()
    for relative in sorted(desired):
        source = staging / relative
        if not source.is_file():
            raise ValueError(f"Restore archive is missing {relative}.")
        target = root / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        _write_private(temporary, source.read_bytes())
        temporary.replace(target)
        os.chmod(target, 0o600)
