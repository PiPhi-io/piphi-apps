from __future__ import annotations

import pytest

from piphi_network_zigbee2mqtt.routes.config import _runtime_config_payloads
from piphi_network_zigbee2mqtt.schemas import DeviceConfig
from piphi_network_zigbee2mqtt.state import apply_config, sidecar_store


class RuntimeConfigLike:
    def model_dump(self, *, mode: str):
        assert mode == "python"
        return {
            "id": "bridge-config",
            "config_id": "bridge-config",
            "container_id": "runtime-container",
            "serial_port": "/dev/ttyUSB0",
            "mqtt_server": "mqtt://user:pass@127.0.0.1:1883",
            "mqtt_base_topic": "zigbee2mqtt",
            "data_path": "/app/data",
        }


def test_runtime_config_payloads_normalizes_runtime_config_models() -> None:
    raw = {"id": "raw-config", "serial_port": "/dev/ttyUSB1"}

    payloads = _runtime_config_payloads([RuntimeConfigLike(), raw])

    assert payloads[0]["id"] == "bridge-config"
    assert payloads[0]["mqtt_server"] == "mqtt://user:pass@127.0.0.1:1883"
    assert payloads[1] is raw


@pytest.mark.anyio
async def test_apply_config_writes_zigbee2mqtt_configuration(tmp_path) -> None:
    config = DeviceConfig(
        id="bridge-config",
        config_id="bridge-config",
        container_id="runtime-container",
        serial_port="/dev/ttyUSB0",
        adapter="zstack",
        mqtt_server="mqtt://user:pass@127.0.0.1:1883",
        mqtt_base_topic="zigbee2mqtt",
        data_path=str(tmp_path),
    )

    await apply_config(config)

    config_path = tmp_path / "configuration.yaml"
    yaml = config_path.read_text(encoding="utf-8")
    assert 'server: "mqtt://127.0.0.1:1883"' in yaml
    assert 'user: "user"' in yaml
    assert 'password: "pass"' in yaml
    assert "user:pass@" not in yaml
    assert 'port: "/dev/ttyUSB0"' in yaml
    assert sidecar_store.config_path == str(config_path)
    assert sidecar_store.config_hash
