from __future__ import annotations

import json
import os
import shutil
import zipfile
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
EXCLUDED_TOP_LEVEL = {"backups", "coordinator-claims"}
ENCRYPTED_BACKUP_MAGIC = b"PIPHI-ZIGBEE-AES256-GCM-V1\n"


def create_network_backup(data_path: str, *, adapter_family: str = "unknown") -> NetworkBackupResponse:
    root = _approved_data_root(data_path)
    available = _network_files(root)
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
        archive.writestr(
            BACKUP_METADATA,
            json.dumps(
                {
                    "format": 1,
                    "sidecar_version": INTEGRATION_VERSION,
                    "zigbee2mqtt_version": "2.14.3",
                    "adapter_family": adapter_family,
                    "created_at": datetime.now(UTC).isoformat(),
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
            if "configuration.yaml" not in names:
                raise ValueError("Zigbee network backup is missing configuration.yaml.")
            if BACKUP_METADATA not in names:
                raise ValueError("Zigbee network backup is missing compatibility metadata.")
            if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
                raise ValueError("Zigbee network backup contains unsafe paths.")
            metadata = json.loads(archive.read(BACKUP_METADATA))
            if not isinstance(metadata, dict) or metadata.get("format") != 1:
                raise ValueError("Zigbee network backup metadata is unsupported.")
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
) -> NetworkRestoreResponse:
    root = _approved_data_root(data_path)
    metadata = inspect_network_backup(backup_path, expected_sha256)
    backup_family = str(metadata.get("adapter_family") or "unknown")
    explicit_evidence = (compatibility_evidence or "").strip()
    if backup_family == "unknown" or (
        backup_family != adapter_family and not explicit_evidence
    ):
        raise ValueError(
            f"Backup adapter family {backup_family!r} is not compatible with {adapter_family!r}."
        )
    rollback = create_network_backup(
        str(root),
        adapter_family=rollback_adapter_family or adapter_family,
    )
    staging = Path(mkdtemp(prefix=".restore-", dir=root))
    rollback_staging: Path | None = None
    try:
        _extract_backup(Path(backup_path), staging)
        restored_files = [str(item) for item in metadata["files"]]
        _replace_data_files(root, staging, restored_files)
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
