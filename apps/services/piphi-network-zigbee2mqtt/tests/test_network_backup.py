from __future__ import annotations

import os

import pytest

from piphi_network_zigbee2mqtt.network_backup import (
    create_network_backup,
    restore_network_backup,
    verify_network_backup,
)


def test_network_backup_is_private_and_checksum_verified(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced:\n  network_key: secret\n", encoding="utf-8")
    (tmp_path / "coordinator_backup.json").write_text("{}", encoding="utf-8")

    result = create_network_backup(str(tmp_path), adapter_family="ember")

    target = tmp_path / "backups" / os.path.basename(result.backup_path)
    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o600
    assert set(result.files) == {"configuration.yaml", "coordinator_backup.json"}
    verify_network_backup(result.backup_path, result.backup_sha256)


def test_network_backup_rejects_tampering(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n", encoding="utf-8")
    result = create_network_backup(str(tmp_path))
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
    nested = tmp_path / "devices" / "state.json"
    nested.parent.mkdir()
    nested.write_text('{"device": 1}', encoding="utf-8")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")
    (tmp_path / "configuration.yaml").write_text("version: changed\n", encoding="utf-8")
    nested.unlink()

    with pytest.raises(ValueError, match="not compatible"):
        restore_network_backup(
            data_path=str(tmp_path),
            backup_path=backup.backup_path,
            expected_sha256=backup.backup_sha256,
            adapter_family="zstack",
        )

    result = restore_network_backup(
        data_path=str(tmp_path),
        backup_path=backup.backup_path,
        expected_sha256=backup.backup_sha256,
        adapter_family="ember",
    )

    assert result.restored is True
    assert (tmp_path / "configuration.yaml").read_text() == "version: original\n"
    assert nested.read_text() == '{"device": 1}'
    assert result.rollback_backup.backup_sha256.startswith("sha256:")
