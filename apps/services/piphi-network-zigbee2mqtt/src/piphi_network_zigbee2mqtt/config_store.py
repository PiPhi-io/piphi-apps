from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from .bridge_models import ConfigWriteResult, ensure_parent_directory


def write_config_atomic(yaml_text: str, config_path: str) -> ConfigWriteResult:
    target = ensure_parent_directory(config_path)
    previous_hash = file_sha256(target) if target.exists() else None
    next_hash = text_sha256(yaml_text)
    if previous_hash == next_hash:
        return ConfigWriteResult(
            config_path=str(target),
            config_hash=next_hash,
            previous_hash=previous_hash,
            changed=False,
        )

    backup_path = None
    if target.exists():
        backup = target.with_suffix(f"{target.suffix}.bak")
        backup.write_bytes(target.read_bytes())
        backup_path = str(backup)

    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(yaml_text, encoding="utf-8")
    temporary.replace(target)
    return ConfigWriteResult(
        config_path=str(target),
        config_hash=next_hash,
        previous_hash=previous_hash,
        changed=True,
        backup_path=backup_path,
    )


def text_sha256(value: str) -> str:
    return f"sha256:{sha256(value.encode('utf-8')).hexdigest()}"


def file_sha256(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"
