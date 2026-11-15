from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from piphi_network_modbus import state
from piphi_network_modbus.profile_codec import encode_point, point_metadata
from piphi_network_modbus.schemas import DeviceConfig


def profile_config(*, transport: str = "tcp") -> DeviceConfig:
    payload: dict[str, Any] = {
        "id": f"composites-{transport}",
        "host": "127.0.0.1",
        "transport": transport,
        "serial_port": "/dev/ttyUSB0" if transport == "rtu_sidecar" else None,
        "points": [
            {"id": "power", "name": "Power", "unit_id": 1, "area": "coil", "address": 0, "data_type": "bool", "writable": True},
            {"id": "brightness", "name": "Brightness", "unit_id": 1, "address": 1, "writable": True, "minimum": 0, "maximum": 100, "unit": "%"},
            {"id": "color_temp", "name": "Color temperature", "unit_id": 1, "address": 2, "writable": True, "minimum": 0, "maximum": 100, "unit": "%"},
            {"id": "mode", "name": "Mode", "unit_id": 1, "address": 3, "writable": True, "enum_values": {"off": 0, "heat": 1, "cool": 2, "auto": 3}},
            {"id": "fan_speed", "name": "Fan speed", "unit_id": 1, "address": 4, "writable": True, "minimum": 0, "maximum": 100, "unit": "%"},
            {"id": "oscillating", "name": "Oscillating", "unit_id": 1, "area": "coil", "address": 1, "data_type": "bool", "writable": True},
            {"id": "cover_position", "name": "Cover position", "unit_id": 1, "address": 5, "writable": True, "minimum": 0, "maximum": 100, "unit": "%"},
            {"id": "cover_command", "name": "Cover command", "unit_id": 1, "address": 6, "writable": True, "enum_values": {"open": 1, "close": 2, "stop": 3}},
            {"id": "cover_state", "name": "Cover state", "unit_id": 1, "address": 7, "enum_values": {"closed": 0, "opening": 1, "closing": 2, "open": 3}},
            {"id": "room_temperature", "name": "Room temperature", "unit_id": 1, "area": "input_register", "address": 8, "data_type": "int16", "scale": 0.1, "unit": "C"},
            {"id": "target_temperature", "name": "Target temperature", "unit_id": 1, "address": 9, "data_type": "int16", "scale": 0.1, "writable": True, "minimum": 5, "maximum": 35, "unit": "C"},
        ],
        "composites": [
            {
                "id": "main_light",
                "name": "Main Light",
                "entity_type": "light",
                "state_points": {"power": "power", "brightness_percent": "brightness", "color_temp_percent": "color_temp", "mode": "mode"},
                "commands": {
                    "turn_on": {"point_id": "power", "value": True},
                    "turn_off": {"point_id": "power", "value": False},
                    "set_brightness": {"point_id": "brightness", "argument": "brightness"},
                    "set_color_temp": {"point_id": "color_temp", "argument": "color_temp"},
                    "set_mode": {"point_id": "mode", "argument": "mode"},
                },
            },
            {
                "id": "supply_fan",
                "name": "Supply Fan",
                "entity_type": "fan",
                "state_points": {"power": "power", "fan_speed_percent": "fan_speed", "oscillating": "oscillating", "mode": "mode"},
                "commands": {
                    "turn_on": {"point_id": "power", "value": True},
                    "turn_off": {"point_id": "power", "value": False},
                    "set_fan_speed": {"point_id": "fan_speed", "argument": "speed"},
                    "set_oscillate": {"point_id": "oscillating", "argument": "oscillating"},
                    "set_mode": {"point_id": "mode", "argument": "mode"},
                },
            },
            {
                "id": "window_cover",
                "name": "Window Cover",
                "entity_type": "cover",
                "state_points": {"position_percent": "cover_position", "movement_state": "cover_state"},
                "commands": {
                    "open_cover": {"point_id": "cover_command", "value": "open"},
                    "close_cover": {"point_id": "cover_command", "value": "close"},
                    "stop_cover": {"point_id": "cover_command", "value": "stop"},
                    "set_cover_position": {"point_id": "cover_position", "argument": "position"},
                },
            },
            {
                "id": "room_climate",
                "name": "Room Climate",
                "entity_type": "climate",
                "state_points": {"power": "power", "temperature_c": "room_temperature", "target_temperature_c": "target_temperature", "mode": "mode", "fan_speed_percent": "fan_speed"},
                "commands": {
                    "turn_on": {"point_id": "power", "value": True},
                    "turn_off": {"point_id": "power", "value": False},
                    "set_temperature": {"point_id": "target_temperature", "argument": "temperature_c"},
                    "set_mode": {"point_id": "mode", "argument": "mode"},
                    "set_fan_speed": {"point_id": "fan_speed", "argument": "speed"},
                },
            },
        ],
    }
    return DeviceConfig.model_validate(payload)


class FakeTCPClient:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {
            "power": False,
            "brightness": 25,
            "color_temp": 50,
            "mode": "heat",
            "fan_speed": 40,
            "oscillating": False,
            "cover_position": 10,
            "cover_command": "stop",
            "cover_state": "closed",
            "room_temperature": 21.5,
            "target_temperature": 22.0,
        }
        self.writes: list[tuple[str, Any]] = []

    async def snapshot(self, points):
        now = datetime.now(UTC).isoformat()
        return {
            "connected": True,
            "responsive_unit_ids": [1],
            "request_count": 1,
            "last_error_code": None,
            "points": [
                {
                    **point_metadata(point),
                    "value": self.values[point.id],
                    "quality": "good",
                    "updated_at": now,
                    "error_code": None,
                }
                for point in points
            ],
        }

    async def write_point(self, point, value):
        encode_point(point, value)
        self.values[point.id] = value
        self.writes.append((point.id, value))
        return value

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_composite_entities_and_tcp_commands_are_profile_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeTCPClient()
    monkeypatch.setattr(state, "tcp_client_factory", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = profile_config()
    await state.apply_config(config)
    try:
        entities = {entity["id"]: entity for entity in state.all_entities()}
        for entity_id, entity_type in {
            "composites-tcp:main_light": "light",
            "composites-tcp:supply_fan": "fan",
            "composites-tcp:window_cover": "cover",
            "composites-tcp:room_climate": "climate",
        }.items():
            assert entities[entity_id]["entity_type"] == entity_type
            assert entities[entity_id]["device_class"] == entity_type
            assert entities[entity_id]["state"]["quality"] == "good"

        climate = entities["composites-tcp:room_climate"]
        assert climate["state"]["temperature_c"] == 21.5
        assert climate["state"]["target_temperature_c"] == 22.0
        assert {command["id"] for command in climate["available_commands"]} == {
            "refresh", "turn_on", "turn_off", "set_temperature", "set_mode", "set_fan_speed"
        }

        result = await state.execute_tcp_command(
            config_id="composites-tcp",
            device_id="composites-tcp:room_climate",
            command="set_temperature",
            args={"temperature_c": 23.5, "address": 65535, "unit_id": 247},
        )
        assert result["point_id"] == "target_temperature"
        assert client.writes[-1] == ("target_temperature", 23.5)

        await state.execute_tcp_command(
            config_id="composites-tcp",
            device_id="composites-tcp:window_cover",
            command="open_cover",
            args={"value": "caller-cannot-override"},
        )
        assert client.writes[-1] == ("cover_command", "open")
    finally:
        await state.remove_config("composites-tcp")


def test_composite_profile_rejects_unsafe_or_ambiguous_bindings() -> None:
    payload = profile_config().model_dump()
    payload["composites"][0]["commands"]["set_brightness"]["point_id"] = "missing"
    with pytest.raises(ValidationError, match="unknown points"):
        DeviceConfig.model_validate(payload)

    payload = profile_config().model_dump()
    payload["composites"][0]["commands"]["set_brightness"] = {
        "point_id": "brightness",
        "value": 50,
    }
    with pytest.raises(ValidationError, match="requires brightness"):
        DeviceConfig.model_validate(payload)

    payload = profile_config().model_dump()
    payload["composites"][0]["commands"]["turn_on"]["point_id"] = "room_temperature"
    with pytest.raises(ValidationError, match="requires a writable point"):
        DeviceConfig.model_validate(payload)

    payload = profile_config().model_dump()
    payload["composites"][0]["state_points"]["power"] = "brightness"
    with pytest.raises(ValidationError, match="incompatible point type"):
        DeviceConfig.model_validate(payload)

    payload = profile_config().model_dump()
    payload["composites"][2]["commands"]["open_cover"]["value"] = "invalid"
    with pytest.raises(ValidationError, match="reviewed enum label"):
        DeviceConfig.model_validate(payload)
