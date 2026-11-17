from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4


class CoordinatorClaimConflict(RuntimeError):
    pass


def stable_coordinator_identity(adapter_identity: str) -> str:
    token = str(adapter_identity or "").strip()
    if not token:
        raise ValueError("A stable coordinator identity is required.")
    return f"coordinator:{sha256(token.lower().encode()).hexdigest()}"


def claim_owner_id() -> str:
    runtime_identity = str(
        os.getenv("PIPHI_CORE_RUNTIME_ID") or os.getenv("PIPHI_RUNTIME_INSTANCE_ID") or ""
    ).strip()
    if not runtime_identity:
        if os.getenv("PIPHI_ENV", "").lower() == "production":
            raise ValueError("Stable Core runtime identity is not configured.")
        runtime_identity = "development-core-runtime"
    return f"core-runtime:{sha256(runtime_identity.encode()).hexdigest()}"


@dataclass(frozen=True)
class CoordinatorClaim:
    identity: str
    owner_id: str
    generation: int
    issued_at: str
    lease_expires_at: str

    @property
    def expires_at(self) -> datetime:
        return datetime.fromisoformat(self.lease_expires_at).astimezone(UTC)


class CoordinatorClaimStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.getenv("PIPHI_ZIGBEE2MQTT_CLAIM_DIR", "/app/data/coordinator-claims")
        )

    def claim(
        self,
        identity: str,
        owner_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: int = 30,
        expected_generation: int | None = None,
    ) -> CoordinatorClaim:
        current_time = _utc(now)
        if not owner_id.strip():
            raise ValueError("A stable Core runtime owner identity is required.")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("Coordinator claim lease must be between 1 and 300 seconds.")
        with self._locked(identity):
            claim_path = self.claim_path(identity)
            if claim_path.exists():
                current = self._read(claim_path)
                if current.owner_id != owner_id:
                    raise CoordinatorClaimConflict(
                        f"Coordinator is already claimed by another runtime owner ({current.owner_id})."
                    )
                if expected_generation != current.generation:
                    raise CoordinatorClaimConflict(
                        "Coordinator claim generation is required to renew existing ownership."
                    )
                renewed = self._new_claim(
                    identity, owner_id, current.generation, current_time, lease_seconds
                )
                self._write(claim_path, renewed)
                return renewed
            created = self._new_claim(identity, owner_id, 1, current_time, lease_seconds)
            self._write(claim_path, created, exclusive=True)
            return created

    def renew(
        self,
        identity: str,
        owner_id: str,
        generation: int,
        *,
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> CoordinatorClaim:
        self.assert_fence(identity, owner_id, generation, now=now)
        return self.claim(
            identity,
            owner_id,
            now=now,
            lease_seconds=lease_seconds,
            expected_generation=generation,
        )

    def assert_fence(
        self,
        identity: str,
        owner_id: str,
        generation: int,
        *,
        now: datetime | None = None,
    ) -> CoordinatorClaim:
        with self._locked(identity):
            claim = self._read(self.claim_path(identity))
            if claim.owner_id != owner_id or claim.generation != generation:
                raise CoordinatorClaimConflict("Coordinator fencing token is no longer current.")
            if claim.expires_at <= _utc(now):
                raise CoordinatorClaimConflict("Coordinator claim lease has expired.")
            return claim

    def repair_stale(
        self,
        identity: str,
        *,
        requester_owner_id: str,
        expected_generation: int,
        owner_is_live: Callable[[str], bool],
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> CoordinatorClaim:
        current_time = _utc(now)
        with self._locked(identity):
            claim_path = self.claim_path(identity)
            current = self._read(claim_path)
            if current.generation != expected_generation:
                raise CoordinatorClaimConflict("Coordinator claim generation changed during stale repair.")
            if current.expires_at > current_time:
                raise CoordinatorClaimConflict("Coordinator claim lease is not stale.")
            if owner_is_live(current.owner_id):
                raise CoordinatorClaimConflict("Coordinator claim owner is still live; refusing repair.")
            replacement = self._new_claim(
                identity,
                requester_owner_id,
                current.generation + 1,
                current_time,
                lease_seconds,
            )
            self._write(claim_path, replacement)
            return replacement

    def release(self, identity: str, owner_id: str, generation: int | None = None) -> bool:
        with self._locked(identity):
            claim_path = self.claim_path(identity)
            if not claim_path.exists():
                return False
            current = self._read(claim_path)
            if current.owner_id != owner_id or (
                generation is not None and current.generation != generation
            ):
                return False
            claim_path.unlink()
            return True

    def get(self, identity: str) -> CoordinatorClaim | None:
        with self._locked(identity):
            path = self.claim_path(identity)
            return self._read(path) if path.exists() else None

    def claim_path(self, identity: str) -> Path:
        return self.path / sha256(identity.encode()).hexdigest()

    @contextmanager
    def _locked(self, identity: str) -> Iterator[None]:
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path, 0o700)
        lock_path = self.path / f".{sha256(identity.encode()).hexdigest()}.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _read(self, claim_path: Path) -> CoordinatorClaim:
        try:
            payload = json.loads(claim_path.read_text(encoding="utf-8"))
            claim = CoordinatorClaim(**payload)
            if claim.generation < 1 or not claim.owner_id or not claim.identity:
                raise ValueError
            _ = claim.expires_at
            return claim
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CoordinatorClaimConflict(
                "Coordinator claim state is invalid or unreadable; refusing ownership."
            ) from exc

    def _write(
        self, claim_path: Path, claim: CoordinatorClaim, *, exclusive: bool = False
    ) -> None:
        flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
        temporary = claim_path.with_name(f".{claim_path.name}.{uuid4().hex}.tmp")
        target = temporary if not exclusive else claim_path
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(claim), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if not exclusive:
            temporary.replace(claim_path)
        os.chmod(claim_path, 0o600)

    @staticmethod
    def _new_claim(
        identity: str,
        owner_id: str,
        generation: int,
        now: datetime,
        lease_seconds: int,
    ) -> CoordinatorClaim:
        return CoordinatorClaim(
            identity=identity,
            owner_id=owner_id,
            generation=generation,
            issued_at=now.isoformat(),
            lease_expires_at=(now + timedelta(seconds=lease_seconds)).isoformat(),
        )


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Coordinator claim timestamps must include a timezone.")
    return result.astimezone(UTC)


claim_store = CoordinatorClaimStore()
