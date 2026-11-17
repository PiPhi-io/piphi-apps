from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from piphi_network_zigbee2mqtt.bridge_models import NetworkRestoreRequest
from piphi_network_zigbee2mqtt.coordinator_claims import CoordinatorClaimStore
from piphi_network_zigbee2mqtt.main import app
from piphi_network_zigbee2mqtt.network_backup import create_network_backup
from piphi_network_zigbee2mqtt.routes import bridge
from piphi_network_zigbee2mqtt.stopped_coordinator_evidence import (
    StoppedCoordinatorEvidence,
    StoppedCoordinatorEvidenceLedger,
    verify_stopped_coordinator_evidence,
)

_SECRET = "test-stopped-coordinator-evidence-key-with-at-least-32-bytes"
_IDENTITY = "serial-by-id:usb-sonoff-123"


def _evidence(
    *,
    now: datetime,
    operation: str = "network_restore",
    identity: str = _IDENTITY,
    nonce: str = "stop.test-1",
    expires_at: datetime | None = None,
) -> StoppedCoordinatorEvidence:
    payload = {
        "protocol": "piphi.zigbee2mqtt.stopped-coordinator.v1",
        "operation": operation,
        "coordinator_identity": identity,
        "generation": 42,
        "target_digest": "1" * 64,
        "helper_spec_digest": "2" * 64,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (expires_at or now + timedelta(seconds=30)).isoformat().replace(
            "+00:00", "Z"
        ),
        "nonce": nonce,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["signature"] = hmac.new(
        _SECRET.encode(), canonical, hashlib.sha256
    ).hexdigest()
    return StoppedCoordinatorEvidence.model_validate(payload)


def test_verified_evidence_is_single_use(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_KEY", _SECRET)
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    evidence = _evidence(now=now)
    ledger = StoppedCoordinatorEvidenceLedger(tmp_path / "evidence.sqlite3")

    verify_stopped_coordinator_evidence(
        evidence,
        operation="network_restore",
        coordinator_identity=_IDENTITY,
        now=now,
        ledger=ledger,
    )

    with pytest.raises(ValueError, match="already been used"):
        verify_stopped_coordinator_evidence(
            evidence,
            operation="network_restore",
            coordinator_identity=_IDENTITY,
            now=now,
            ledger=ledger,
        )


@pytest.mark.parametrize(
    ("updates", "operation", "identity", "message"),
    [
        ({"signature": "f" * 64}, "network_restore", _IDENTITY, "authentication failed"),
        ({}, "coordinator_migration_apply", _IDENTITY, "does not authorize"),
        ({}, "network_restore", "serial-by-id:other", "does not match"),
    ],
)
def test_evidence_rejects_forgery_or_mismatch(
    tmp_path,
    monkeypatch,
    updates,
    operation,
    identity,
    message,
) -> None:
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_KEY", _SECRET)
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    evidence = _evidence(now=now).model_copy(update=updates)

    with pytest.raises(ValueError, match=message):
        verify_stopped_coordinator_evidence(
            evidence,
            operation=operation,
            coordinator_identity=identity,
            now=now,
            ledger=StoppedCoordinatorEvidenceLedger(tmp_path / "evidence.sqlite3"),
        )


def test_evidence_rejects_expiry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_KEY", _SECRET)
    issued_at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    evidence = _evidence(now=issued_at, expires_at=issued_at + timedelta(seconds=5))

    with pytest.raises(ValueError, match="stale or expired"):
        verify_stopped_coordinator_evidence(
            evidence,
            operation="network_restore",
            coordinator_identity=_IDENTITY,
            now=issued_at + timedelta(seconds=6),
            ledger=StoppedCoordinatorEvidenceLedger(tmp_path / "evidence.sqlite3"),
        )


def test_core_managed_restore_rejects_missing_evidence() -> None:
    with pytest.raises(ValidationError, match="requires stopped-coordinator evidence"):
        NetworkRestoreRequest.model_validate(
            {
                "data_path": "/app/data",
                "backup_path": "/app/data/backups/network.tar.gz",
                "backup_sha256": "1" * 64,
                "adapter_family": "zstack",
                "coordinator_identity": _IDENTITY,
                "coordinator_port": "/dev/serial/by-id/usb-sonoff-123",
                "coordinator_stop_authority": "core_managed_helper",
                "confirm_restore": True,
            }
        )


@pytest.mark.anyio
async def test_managed_restore_uses_verified_evidence_instead_of_local_probe(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_KEY", _SECRET)
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_LEDGER_PATH", str(tmp_path / "evidence.db"))
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(bridge, "claim_store", CoordinatorClaimStore(tmp_path / "claims"))
    monkeypatch.setattr(
        bridge,
        "probe_coordinator",
        lambda _port: (_ for _ in ()).throw(AssertionError("local probe must not run")),
    )
    (tmp_path / "configuration.yaml").write_text("before: true\n")
    (tmp_path / "database.db").write_text("device")
    (tmp_path / "coordinator_backup.json").write_text("{}")
    backup = create_network_backup(str(tmp_path), adapter_family="zstack", workload_fenced=True)
    (tmp_path / "configuration.yaml").write_text("after: true\n")
    evidence = _evidence(now=datetime.now(UTC), nonce="stop.route-test")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/network-restore",
            json={
                "data_path": str(tmp_path),
                "backup_path": backup.backup_path,
                "backup_sha256": backup.backup_sha256,
                "adapter_family": "zstack",
                "coordinator_identity": _IDENTITY,
                "coordinator_port": "/dev/serial/by-id/usb-sonoff-123",
                "coordinator_stop_authority": "core_managed_helper",
                "stopped_coordinator_evidence": evidence.model_dump(mode="json"),
                "confirm_restore": True,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["restored"] is True
    assert (tmp_path / "configuration.yaml").read_text() == "before: true\n"
