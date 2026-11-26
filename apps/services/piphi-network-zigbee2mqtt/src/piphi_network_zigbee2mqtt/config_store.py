from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from .bridge_models import ConfigWriteResult


def write_config_atomic(yaml_text: str, config_path: str) -> ConfigWriteResult:
    target = Path(config_path).expanduser()
    require_allowed_config_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = file_sha256(target) if target.exists() else None
    next_hash = text_sha256(yaml_text)
    if previous_hash == next_hash:
        os.chmod(target, 0o600)
        return ConfigWriteResult(
            config_path=str(target),
            config_hash=next_hash,
            previous_hash=previous_hash,
            changed=False,
        )

    backup_path = None
    if target.exists():
        backup = target.with_suffix(f"{target.suffix}.bak")
        _write_private(backup, target.read_bytes())
        backup_path = str(backup)

    temporary = target.with_suffix(f"{target.suffix}.tmp")
    _write_private(temporary, yaml_text.encode("utf-8"))
    temporary.replace(target)
    os.chmod(target, 0o600)
    return ConfigWriteResult(
        config_path=str(target),
        config_hash=next_hash,
        previous_hash=previous_hash,
        changed=True,
        backup_path=backup_path,
    )


def rollback_config_write(result: ConfigWriteResult) -> None:
    target = Path(result.config_path)
    require_allowed_config_path(target)
    if not result.changed:
        return
    if result.backup_path:
        backup = Path(result.backup_path)
        if not backup.is_file():
            raise OSError("Configuration rollback backup is missing.")
        _write_private(target, backup.read_bytes())
    else:
        target.unlink(missing_ok=True)


def text_sha256(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def require_allowed_config_path(target: Path) -> None:
    configured = os.getenv(
        "PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS",
        f"/app/data{os.pathsep}/var/lib/piphi/zigbee2mqtt",
    )
    roots = [Path(value).expanduser().resolve() for value in configured.split(os.pathsep) if value]
    resolved = target.expanduser().resolve()
    if not roots or not any(resolved == root / "configuration.yaml" for root in roots):
        raise ValueError("config_path must be configuration.yaml in an approved Zigbee2MQTT data root.")


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    os.chmod(path, 0o600)


def file_sha256(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"
