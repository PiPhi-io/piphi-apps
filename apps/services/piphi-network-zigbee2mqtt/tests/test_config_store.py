from __future__ import annotations

from piphi_network_zigbee2mqtt.config_store import write_config_atomic


def test_write_config_atomic_tracks_hash_and_change_state(tmp_path) -> None:
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
