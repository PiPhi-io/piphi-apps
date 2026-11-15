from __future__ import annotations

import pytest

from piphi_network_zigbee2mqtt.config_store import write_config_atomic


def test_write_config_atomic_tracks_hash_and_change_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    target = tmp_path / "configuration.yaml"

    first = write_config_atomic("mqtt:\n  base_topic: zigbee2mqtt\n", str(target))
    second = write_config_atomic("mqtt:\n  base_topic: zigbee2mqtt\n", str(target))
    third = write_config_atomic("mqtt:\n  base_topic: piphi\n", str(target))

    assert first.changed is True
    assert first.previous_hash is None
    assert second.changed is False
    assert second.previous_hash == first.config_hash
    assert third.changed is True
    assert third.previous_hash == first.config_hash
    assert third.backup_path is not None
    assert (target.stat().st_mode & 0o777) == 0o600
    assert (target.with_suffix(".yaml.bak").stat().st_mode & 0o777) == 0o600


def test_write_config_rejects_unapproved_path(tmp_path, monkeypatch) -> None:
    approved = tmp_path / "approved"
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(approved))

    with pytest.raises(ValueError, match="approved Zigbee2MQTT data root"):
        write_config_atomic("mqtt: {}\n", str(tmp_path / "configuration.yaml"))
