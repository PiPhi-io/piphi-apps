from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


class CoordinatorClaimConflict(RuntimeError):
    pass


def stable_coordinator_identity(adapter_identity: str) -> str:
    token = str(adapter_identity or "").strip()
    if not token:
        raise ValueError("A stable coordinator identity is required.")
    normalized = token.lower()
    return f"coordinator:{sha256(normalized.encode()).hexdigest()}"


_RUNTIME_OWNER_ID = os.getenv("PIPHI_RUNTIME_INSTANCE_ID") or f"zigbee2mqtt-sidecar:{uuid4()}"


def claim_owner_id() -> str:
    return _RUNTIME_OWNER_ID


class CoordinatorClaimStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.getenv("PIPHI_ZIGBEE2MQTT_CLAIM_DIR", "/app/data/coordinator-claims")
        )

    def claim(self, identity: str, owner_id: str) -> None:
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path, 0o700)
        claim_path = self.claim_path(identity)
        try:
            descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            current = self._read_owner(claim_path)
            if current == owner_id:
                return
            raise CoordinatorClaimConflict(
                f"Coordinator is already claimed by another runtime owner ({current})."
            )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(owner_id)

    def release(self, identity: str, owner_id: str) -> bool:
        claim_path = self.claim_path(identity)
        if not claim_path.exists() or self._read_owner(claim_path) != owner_id:
            return False
        claim_path.unlink()
        return True

    def claim_path(self, identity: str) -> Path:
        return self.path / sha256(identity.encode()).hexdigest()

    def _read_owner(self, claim_path: Path) -> str:
        try:
            owner = claim_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise CoordinatorClaimConflict("Coordinator claim state is unreadable; refusing ownership.") from exc
        if not owner:
            raise CoordinatorClaimConflict("Coordinator claim state is invalid; refusing ownership.")
        return owner


claim_store = CoordinatorClaimStore()
