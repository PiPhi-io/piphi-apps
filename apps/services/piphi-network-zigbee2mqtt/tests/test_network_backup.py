from __future__ import annotations

import os
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from piphi_network_zigbee2mqtt.network_backup import (
    create_network_backup,
    export_encrypted_backup,
    import_encrypted_backup,
    inspect_network_backup,
    restore_network_backup,
    verify_network_backup,
)


def _recoverable_data(root, *, coordinator_backup: bool = False) -> None:
    (root / "configuration.yaml").write_text("advanced: {}\n", encoding="utf-8")
    (root / "database.db").write_text("0x00124b: device\n", encoding="utf-8")
    if coordinator_backup:
        (root / "coordinator_backup.json").write_text('{"metadata": {}}', encoding="utf-8")


def test_backup_requires_database_and_fresh_upstream_coordinator_backup_when_supported(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n")

    with pytest.raises(ValueError, match="database.db"):
        create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)

    (tmp_path / "database.db").write_text("device")
    old_backup = tmp_path / "coordinator_backup.json"
    old_backup.write_text("{}")
    old = (datetime.now(UTC) - timedelta(minutes=10)).timestamp()
    os.utime(old_backup, (old, old))
    with pytest.raises(ValueError, match="fresh upstream coordinator backup"):
        create_network_backup(
            str(tmp_path),
            adapter_family="ember",
            adapter_backup_supported=True,
            workload_fenced=True,
        )

    old_backup.write_text('{"metadata": {}}')
    result = create_network_backup(
        str(tmp_path),
        adapter_family="ember",
        adapter_backup_supported=True,
        workload_fenced=True,
        zigbee2mqtt_version="2.14.3",
    )
    metadata = inspect_network_backup(result.backup_path, result.backup_sha256)
    assert metadata["recoverable"] is True
    assert metadata["adapter_family"] == "ember"
    assert metadata["zigbee2mqtt_version"] == "2.14.3"
    assert metadata["coordinator_backup_created_at"]


def test_restore_verification_hook_failure_rolls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    _recoverable_data(tmp_path, coordinator_backup=True)
    backup = create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)
    (tmp_path / "configuration.yaml").write_text("current: true\n")

    with pytest.raises(ValueError, match="post-restore verification"):
        restore_network_backup(
            data_path=str(tmp_path),
            backup_path=backup.backup_path,
            expected_sha256=backup.backup_sha256,
            adapter_family="ember",
            workload_fenced=True,
            post_restore_verify=lambda _root, _metadata: False,
        )

    assert (tmp_path / "configuration.yaml").read_text() == "current: true\n"


def test_network_backup_is_private_and_checksum_verified(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced:\n  network_key: secret\n", encoding="utf-8")
    (tmp_path / "database.db").write_text("device", encoding="utf-8")
    (tmp_path / "coordinator_backup.json").write_text("{}", encoding="utf-8")

    result = create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)

    target = tmp_path / "backups" / os.path.basename(result.backup_path)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600
    assert set(result.files) == {"configuration.yaml", "database.db", "coordinator_backup.json"}
    verify_network_backup(result.backup_path, result.backup_sha256)


def test_network_backup_excludes_sidecar_control_plane_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("serial: {}\n", encoding="utf-8")
    (tmp_path / "database.db").write_text("device", encoding="utf-8")
    (tmp_path / "coordinator_backup.json").write_text("{}", encoding="utf-8")
    control_plane = tmp_path / "piphi-sidecar"
    control_plane.mkdir()
    (control_plane / "coordinator-stop-evidence.sqlite3").write_bytes(b"nonce-ledger")
    (control_plane / "automation-actions.sqlite3").write_bytes(b"action-ledger")

    result = create_network_backup(str(tmp_path), adapter_family="zstack", workload_fenced=True)

    assert result.files == ["configuration.yaml", "coordinator_backup.json", "database.db"]
    target = tmp_path / "backups" / os.path.basename(result.backup_path)
    with zipfile.ZipFile(target) as archive:
        assert not any(name.startswith("piphi-sidecar/") for name in archive.namelist())


def test_network_backup_rejects_tampering(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n", encoding="utf-8")
    (tmp_path / "database.db").write_text("device", encoding="utf-8")
    result = create_network_backup(
        str(tmp_path), adapter_family="deconz", workload_fenced=True
    )
    with open(result.backup_path, "ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(ValueError, match="checksum"):
        verify_network_backup(result.backup_path, result.backup_sha256)


def test_network_restore_checks_adapter_compatibility_and_restores_full_data(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("version: original\n", encoding="utf-8")
    (tmp_path / "database.db").write_text("device", encoding="utf-8")
    (tmp_path / "coordinator_backup.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "devices" / "state.json"
    nested.parent.mkdir()
    nested.write_text('{"device": 1}', encoding="utf-8")
    backup = create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)
    (tmp_path / "configuration.yaml").write_text("version: changed\n", encoding="utf-8")
    nested.unlink()

    with pytest.raises(ValueError, match="not compatible"):
        restore_network_backup(
            data_path=str(tmp_path),
            backup_path=backup.backup_path,
            expected_sha256=backup.backup_sha256,
            adapter_family="zstack",
            workload_fenced=True,
        )

    result = restore_network_backup(
        data_path=str(tmp_path),
        backup_path=backup.backup_path,
        expected_sha256=backup.backup_sha256,
        adapter_family="ember",
        workload_fenced=True,
    )

    assert result.restored is True
    assert (tmp_path / "configuration.yaml").read_text() == "version: original\n"
    assert nested.read_text() == '{"device": 1}'
    assert result.rollback_backup.backup_sha256.startswith("sha256:")


def test_encrypted_backup_round_trip_and_wrong_passphrase_fail_closed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced:\n  network_key: secret\n")
    (tmp_path / "database.db").write_text("device")
    (tmp_path / "coordinator_backup.json").write_text("{}")
    backup = create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)

    exported = export_encrypted_backup(
        backup_path=backup.backup_path,
        expected_sha256=backup.backup_sha256,
        passphrase="a sufficiently long passphrase",
    )

    encrypted = (tmp_path / "exports" / os.path.basename(exported.export_path)).read_bytes()
    assert b"network_key: secret" not in encrypted
    assert (os.stat(exported.export_path).st_mode & 0o777) == 0o600
    with pytest.raises(ValueError, match="passphrase or authentication"):
        import_encrypted_backup(
            data_path=str(tmp_path),
            export_path=exported.export_path,
            expected_sha256=exported.export_sha256,
            passphrase="the wrong passphrase value",
        )

    imported = import_encrypted_backup(
        data_path=str(tmp_path),
        export_path=exported.export_path,
        expected_sha256=exported.export_sha256,
        passphrase="a sufficiently long passphrase",
    )

    verify_network_backup(imported.backup_path, imported.backup_sha256)
    assert set(imported.files) == {
        "configuration.yaml",
        "coordinator_backup.json",
        "database.db",
    }


def test_encrypted_backup_rejects_ciphertext_tampering(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n")
    (tmp_path / "database.db").write_text("device")
    (tmp_path / "coordinator_backup.json").write_text("{}")
    backup = create_network_backup(str(tmp_path), adapter_family="ember", workload_fenced=True)
    exported = export_encrypted_backup(
        backup_path=backup.backup_path,
        expected_sha256=backup.backup_sha256,
        passphrase="a sufficiently long passphrase",
    )
    target = tmp_path / "exports" / os.path.basename(exported.export_path)
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 1
    target.write_bytes(payload)

    with pytest.raises(ValueError, match="checksum"):
        import_encrypted_backup(
            data_path=str(tmp_path),
            export_path=exported.export_path,
            expected_sha256=exported.export_sha256,
            passphrase="a sufficiently long passphrase",
        )
