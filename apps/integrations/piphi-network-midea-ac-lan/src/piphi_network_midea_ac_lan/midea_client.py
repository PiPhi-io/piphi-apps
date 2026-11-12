from __future__ import annotations

from importlib import import_module
from math import isfinite
from typing import Any

ALLOWED_HVAC_MODES = {"auto", "cool", "heat", "dry", "fan_only"}
ALLOWED_FAN_MODES = {"auto", "silent", "low", "medium", "high", "max"}
ALLOWED_SWING_MODES = {"off", "vertical", "horizontal", "both"}
ALLOWED_PRESET_MODES = {"none", "sleep", "eco", "boost", "away"}
FAN_MODE_ORDER = ("auto", "silent", "low", "medium", "high", "max")
SWING_MODE_ORDER = ("off", "vertical", "horizontal", "both")
PRESET_MODE_ORDER = ("none", "sleep", "eco", "boost", "away")


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    return str(name if name is not None else value).strip().lower()


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _supported_names(device: Any, attribute: str) -> set[str]:
    values = getattr(device, attribute, None) or []
    return {name for value in values if (name := _enum_name(value))}


def _enum_member(device: Any, enum_name: str, member: str) -> Any:
    enum_type = getattr(device, enum_name, None)
    if enum_type is None:
        raise ValueError(f"The device library does not expose {enum_name}")
    try:
        return getattr(enum_type, member.upper())
    except AttributeError as exc:
        raise ValueError(f"Unsupported {enum_name}: {member}") from exc


def _derived_hvac_action(state: dict[str, Any]) -> str:
    if not state.get("power"):
        return "off"
    mode = str(state.get("hvac_mode") or "auto")
    if mode == "dry":
        return "drying"
    if mode == "fan_only":
        return "fan"
    indoor = _finite_number(state.get("indoor_temperature_c"))
    target = _finite_number(state.get("target_temperature_c"))
    if indoor is None or target is None:
        return "idle"
    if mode == "cool":
        return "cooling" if indoor > target + 0.5 else "idle"
    if mode == "heat":
        return "heating" if indoor < target - 0.5 else "idle"
    if mode == "auto":
        if indoor > target + 0.5:
            return "cooling"
        if indoor < target - 0.5:
            return "heating"
    return "idle"


class MideaLanClient:
    """Narrow, testable adapter around msmart-ng's async AC API."""

    def __init__(self, device: Any) -> None:
        self._device = device

    @classmethod
    async def connect(
        cls,
        *,
        host: str,
        port: int = 6444,
        device_id: int | None = None,
        token: str | None = None,
        key: str | None = None,
    ) -> MideaLanClient:
        if bool(token) != bool(key):
            raise ValueError("token and key must be configured together")
        if device_id is None:
            discover = import_module("msmart.discover").Discover
            device = await discover.discover_single(host)
            if device is None:
                raise ConnectionError("No supported Midea AC responded at the configured host")
        else:
            air_conditioner = import_module("msmart.device").AirConditioner
            device = air_conditioner(ip=host, port=port, device_id=device_id)
        if token and key:
            await device.authenticate(token, key)

        if not bool(getattr(device, "supported", True)):
            raise ValueError("The discovered device is not a supported Midea air conditioner")
        await device.get_capabilities()
        await device.refresh()
        return cls(device)

    async def refresh(self) -> dict[str, Any]:
        await self._device.refresh()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "connected": bool(getattr(self._device, "online", True)),
            "power": bool(getattr(self._device, "power_state", False)),
        }
        mode = _enum_name(getattr(self._device, "operational_mode", None))
        if mode:
            state["hvac_mode"] = mode
        for capability, attribute in (
            ("target_temperature_c", "target_temperature"),
            ("indoor_temperature_c", "indoor_temperature"),
            ("outdoor_temperature_c", "outdoor_temperature"),
        ):
            value = _finite_number(getattr(self._device, attribute, None))
            if value is not None:
                state[capability] = value
        fan_speed = getattr(self._device, "fan_speed", None)
        fan_mode = _enum_name(fan_speed)
        supported_fan_modes = _supported_names(
            self._device, "supported_fan_speeds"
        )
        if supported_fan_modes:
            state["fan_modes_supported"] = ",".join(
                mode for mode in FAN_MODE_ORDER if mode in supported_fan_modes
            )
        if fan_mode and supported_fan_modes:
            state["fan_mode"] = (
                fan_mode if fan_mode in ALLOWED_FAN_MODES else "custom"
            )
        fan_value = _finite_number(getattr(fan_speed, "value", fan_speed))
        if fan_value is not None:
            state["fan_speed_percent"] = fan_value
        swing_mode = _enum_name(getattr(self._device, "swing_mode", None))
        supported_swing_modes = _supported_names(
            self._device, "supported_swing_modes"
        )
        if supported_swing_modes:
            state["swing_modes_supported"] = ",".join(
                mode for mode in SWING_MODE_ORDER if mode in supported_swing_modes
            )
        if (
            swing_mode in ALLOWED_SWING_MODES
            and supported_swing_modes - {"off"}
        ):
            state["swing_mode"] = swing_mode
        supported_presets = {"none", "sleep"}
        if bool(getattr(self._device, "supports_eco", False)):
            supported_presets.add("eco")
        if bool(getattr(self._device, "supports_turbo", False)):
            supported_presets.add("boost")
        if bool(getattr(self._device, "supports_freeze_protection", False)):
            supported_presets.add("away")
        state["preset_modes_supported"] = ",".join(
            preset for preset in PRESET_MODE_ORDER if preset in supported_presets
        )
        preset_mode = "none"
        for preset, attribute, support_attribute in (
            ("eco", "eco", "supports_eco"),
            ("boost", "turbo", "supports_turbo"),
            ("away", "freeze_protection", "supports_freeze_protection"),
            ("sleep", "sleep", None),
        ):
            supported = support_attribute is None or bool(
                getattr(self._device, support_attribute, False)
            )
            if supported and bool(getattr(self._device, attribute, False)):
                preset_mode = preset
                break
        state["preset_mode"] = preset_mode
        state["hvac_action"] = _derived_hvac_action(state)
        return state

    async def execute(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if command == "set_power":
            value = args.get("power", args.get("value"))
            if not isinstance(value, bool):
                raise ValueError("set_power requires a boolean power value")
            self._device.power_state = value
        elif command == "set_hvac_mode":
            mode = str(args.get("mode", args.get("value", ""))).strip().lower()
            if mode not in ALLOWED_HVAC_MODES:
                raise ValueError(f"Unsupported HVAC mode: {mode or 'empty'}")
            supported = _supported_names(
                self._device, "supported_operation_modes"
            ) or _supported_names(self._device, "supported_modes")
            if mode not in supported:
                raise ValueError(f"HVAC mode is not supported by this device: {mode}")
            enum_type = self._device.OperationalMode
            self._device.operational_mode = getattr(enum_type, mode.upper())
        elif command == "set_target_temperature":
            temperature = _finite_number(args.get("temperature", args.get("value")))
            if temperature is None:
                raise ValueError("set_target_temperature requires a numeric temperature")
            minimum = _finite_number(getattr(self._device, "min_target_temperature", 16)) or 16
            maximum = _finite_number(getattr(self._device, "max_target_temperature", 30)) or 30
            if not minimum <= temperature <= maximum:
                raise ValueError(
                    f"Target temperature must be between {minimum:g} and {maximum:g} °C"
                )
            self._device.target_temperature = temperature
        elif command == "set_fan_mode":
            fan_mode = str(args.get("fan_mode", args.get("value", ""))).strip().lower()
            if fan_mode not in ALLOWED_FAN_MODES:
                raise ValueError(f"Unsupported fan mode: {fan_mode or 'empty'}")
            supported = _supported_names(self._device, "supported_fan_speeds")
            if fan_mode not in supported:
                raise ValueError(f"Fan mode is not supported by this device: {fan_mode}")
            self._device.fan_speed = _enum_member(self._device, "FanSpeed", fan_mode)
        elif command == "set_swing_mode":
            swing_mode = str(args.get("swing_mode", args.get("value", ""))).strip().lower()
            if swing_mode not in ALLOWED_SWING_MODES:
                raise ValueError(f"Unsupported swing mode: {swing_mode or 'empty'}")
            supported = _supported_names(self._device, "supported_swing_modes")
            if swing_mode not in supported:
                raise ValueError(f"Swing mode is not supported by this device: {swing_mode}")
            self._device.swing_mode = _enum_member(self._device, "SwingMode", swing_mode)
        elif command == "set_preset_mode":
            preset = str(args.get("preset_mode", args.get("value", ""))).strip().lower()
            if preset not in ALLOWED_PRESET_MODES:
                raise ValueError(f"Unsupported preset mode: {preset or 'empty'}")
            support_attributes = {
                "eco": "supports_eco",
                "boost": "supports_turbo",
                "away": "supports_freeze_protection",
            }
            support_attribute = support_attributes.get(preset)
            if support_attribute and not bool(getattr(self._device, support_attribute, False)):
                raise ValueError(f"Preset is not supported by this device: {preset}")
            mode = _enum_name(getattr(self._device, "operational_mode", None))
            allowed_for_mode = {
                "auto": {"none", "sleep", "eco", "boost"},
                "cool": {"none", "sleep", "eco", "boost"},
                "heat": {"none", "sleep", "boost", "away"},
                "dry": {"none", "eco"},
                "fan_only": {"none"},
            }
            if preset not in allowed_for_mode.get(mode or "", {"none"}):
                raise ValueError(
                    f"Preset {preset} is not available in {mode or 'unknown'} mode"
                )
            self._device.eco = preset == "eco"
            self._device.turbo = preset == "boost"
            self._device.freeze_protection = preset == "away"
            self._device.sleep = preset == "sleep"
        else:
            raise ValueError(f"Unsupported command: {command}")

        self._device.beep = False
        await self._device.apply()
        await self._device.refresh()
        return self.snapshot()
