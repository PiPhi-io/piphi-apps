from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StoppedCoordinatorOperation = Literal[
    "network_restore",
    "coordinator_migration_plan",
    "coordinator_migration_apply",
]

_PROTOCOL = "piphi.zigbee2mqtt.stopped-coordinator.v1"
_MAX_LIFETIME = timedelta(seconds=30)
_FUTURE_TOLERANCE = timedelta(seconds=5)


class StoppedCoordinatorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["piphi.zigbee2mqtt.stopped-coordinator.v1"] = _PROTOCOL
    operation: StoppedCoordinatorOperation
    coordinator_identity: str = Field(min_length=1, max_length=256)
    generation: int = Field(ge=1)
    target_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    helper_spec_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$")
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("coordinator_identity")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        identity = value.strip()
        if not identity or not all(character.isprintable() for character in identity):
            raise ValueError("Coordinator identity is invalid.")
        return identity


class StoppedCoordinatorEvidenceLedger:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()

    def consume(self, evidence: StoppedCoordinatorEvidence, *, now: datetime) -> None:
        path = self._path or _default_ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS consumed_evidence "
                "(nonce TEXT PRIMARY KEY, expires_at TEXT NOT NULL)"
            )
            connection.execute(
                "DELETE FROM consumed_evidence WHERE expires_at <= ?",
                (_as_utc(now).isoformat(),),
            )
            try:
                connection.execute(
                    "INSERT INTO consumed_evidence (nonce, expires_at) VALUES (?, ?)",
                    (evidence.nonce, _as_utc(evidence.expires_at).isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Stopped-coordinator evidence has already been used.") from exc


stopped_coordinator_evidence_ledger = StoppedCoordinatorEvidenceLedger()


def verify_stopped_coordinator_evidence(
    evidence: StoppedCoordinatorEvidence,
    *,
    operation: StoppedCoordinatorOperation,
    coordinator_identity: str,
    now: datetime | None = None,
    ledger: StoppedCoordinatorEvidenceLedger | None = None,
) -> None:
    current = _as_utc(now or datetime.now(UTC))
    issued_at = _as_utc(evidence.issued_at)
    expires_at = _as_utc(evidence.expires_at)
    if evidence.operation != operation:
        raise ValueError("Stopped-coordinator evidence does not authorize this operation.")
    if not hmac.compare_digest(evidence.coordinator_identity, coordinator_identity.strip()):
        raise ValueError("Stopped-coordinator evidence does not match the selected coordinator.")
    if issued_at > current + _FUTURE_TOLERANCE:
        raise ValueError("Stopped-coordinator evidence was issued in the future.")
    if expires_at <= current or expires_at <= issued_at or expires_at - issued_at > _MAX_LIFETIME:
        raise ValueError("Stopped-coordinator evidence is stale or expired.")
    expected = _signature(evidence, _evidence_secret())
    if not hmac.compare_digest(evidence.signature, expected):
        raise ValueError("Stopped-coordinator evidence authentication failed.")
    (ledger or stopped_coordinator_evidence_ledger).consume(evidence, now=current)


def _signature(evidence: StoppedCoordinatorEvidence, secret: bytes) -> str:
    payload = evidence.model_dump(mode="json", exclude={"signature"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, canonical, hashlib.sha256).hexdigest()


def _evidence_secret() -> bytes:
    token = str(
        os.getenv("PIPHI_COORDINATOR_EVIDENCE_KEY")
        or os.getenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN")
        or os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN")
        or ""
    ).strip()
    if len(token.encode()) < 32:
        raise ValueError("Stopped-coordinator evidence authentication is not configured.")
    return token.encode()


def _default_ledger_path() -> Path:
    explicit = str(os.getenv("PIPHI_COORDINATOR_EVIDENCE_LEDGER_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    automation = Path(
        os.getenv(
            "PIPHI_AUTOMATION_LEDGER_PATH",
            "/.piphinetwork/automation-actions.sqlite3",
        )
    )
    return automation.with_name("coordinator-stop-evidence.sqlite3")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Stopped-coordinator evidence timestamps must include a timezone.")
    return value.astimezone(UTC)


__all__ = [
    "StoppedCoordinatorEvidence",
    "StoppedCoordinatorEvidenceLedger",
    "StoppedCoordinatorOperation",
    "verify_stopped_coordinator_evidence",
]
