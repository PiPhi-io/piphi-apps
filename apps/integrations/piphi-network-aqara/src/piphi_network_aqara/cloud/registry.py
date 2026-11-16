from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .models import AqaraResourceInfo


@dataclass(frozen=True, slots=True)
class AqaraCapabilityRule:
    capability: str
    resource_ids: tuple[str, ...] = ()
    name_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AqaraCommandRule:
    capability: str
    commands: dict[str, str] = field(default_factory=dict)
    dynamic_command: str | None = None
    argument: str = "value"
    default_minimum: int | None = None
    default_maximum: int | None = None
    require_resource_bounds: bool = False
    whole_number: bool = True


@dataclass(frozen=True, slots=True)
class AqaraModelProfile:
    model_prefixes: tuple[str, ...]
    capability_rules: tuple[AqaraCapabilityRule, ...] = ()
    command_rules: tuple[AqaraCommandRule, ...] = ()

    def matches(self, model: str) -> bool:
        normalized_model = str(model or "").strip().lower()
        return any(normalized_model.startswith(prefix) for prefix in self.model_prefixes)


DEFAULT_CAPABILITY_RULES: tuple[AqaraCapabilityRule, ...] = (
    AqaraCapabilityRule("color_temperature", name_tokens=("color temperature", "colour temperature", "colortemperature")),
    AqaraCapabilityRule("target_temperature_c", name_tokens=("set temperature", "settemperature", "target temperature", "heating temperature", "cooling temperature")),
    AqaraCapabilityRule("temperature_c", name_tokens=("temperature", "temp")),
    AqaraCapabilityRule("humidity_percent", name_tokens=("humidity", "humid")),
    AqaraCapabilityRule("pressure_hpa", name_tokens=("pressure", "barometric")),
    AqaraCapabilityRule("battery_low", name_tokens=("low battery", "battery low", "low power alarm", "battery alarm")),
    AqaraCapabilityRule("battery_percent", name_tokens=("battery", "battery level")),
    AqaraCapabilityRule("illuminance_lux", name_tokens=("illuminance", "lux", "light level")),
    AqaraCapabilityRule("presence_detected", name_tokens=("presence", "occupancy", "occupied")),
    AqaraCapabilityRule("motion_detected", name_tokens=("motion", "movement", "pir")),
    AqaraCapabilityRule("person_detected", name_tokens=("person detected", "human detected", "face detected")),
    AqaraCapabilityRule("audio_detected", name_tokens=("sound detected", "audio detected", "cry detected", "sound alarm")),
    AqaraCapabilityRule("doorbell_pressed", name_tokens=("doorbell ring", "doorbell button", "bell press", "bell ring")),
    AqaraCapabilityRule("contact_open", name_tokens=("contact", "door/window", "door status", "window status", "magnet")),
    AqaraCapabilityRule("leak_detected", name_tokens=("water leak", "leak", "flood")),
    AqaraCapabilityRule("smoke_alarm", name_tokens=("smoke", "fire alarm")),
    AqaraCapabilityRule("gas_alarm", name_tokens=("gas", "lpg", "co alarm", "co detector", "carbon monoxide", "natural gas")),
    AqaraCapabilityRule("co2_ppm", name_tokens=("co2",)),
    AqaraCapabilityRule("voc_ppb", name_tokens=("tvoc", "voc")),
    AqaraCapabilityRule("pm1_ugm3", name_tokens=("pm1.0", "pm1 density")),
    AqaraCapabilityRule("pm25_ugm3", name_tokens=("pm2.5", "pm25")),
    AqaraCapabilityRule("pm10_ugm3", name_tokens=("pm10", "pm10 density")),
    AqaraCapabilityRule("carbon_monoxide_detected", name_tokens=("carbon monoxide detected", "co detected")),
    AqaraCapabilityRule("filter_life_percent", name_tokens=("filter remaining life", "filter life")),
    AqaraCapabilityRule("power_w", resource_ids=("8.0.2001",), name_tokens=("load power", "watt", "active power", "real power")),
    AqaraCapabilityRule("energy_kwh", resource_ids=("8.0.2002", "8.0.2003"), name_tokens=("power consumption", "energy", "consumption", "electricity")),
    AqaraCapabilityRule("voltage_v", name_tokens=("voltage", "line voltage", "input voltage")),
    AqaraCapabilityRule("current_a", name_tokens=("load current", "electric current", "ampere", "amps")),
    AqaraCapabilityRule("frequency_hz", name_tokens=("frequency", "line frequency", "grid frequency")),
    AqaraCapabilityRule("power_factor", name_tokens=("power factor", "pf")),
    AqaraCapabilityRule(
        "switch_on",
        resource_ids=("4.1.85", "14.7.85"),
        name_tokens=("plug status", "switch status", "on/off", "onoff", "load status", "power switch"),
    ),
    AqaraCapabilityRule("brightness_percent", name_tokens=("brightness", "dimmer", "brightness level", "currentlevel")),
    AqaraCapabilityRule("hue_degrees", name_tokens=("hue", "hue angle")),
    AqaraCapabilityRule("saturation_percent", name_tokens=("saturation", "colour saturation", "color saturation")),
    AqaraCapabilityRule("fan_speed_percent", name_tokens=("fan speed", "fanspeed", "fan level", "air speed")),
    AqaraCapabilityRule("cover_position", name_tokens=("curtain position", "shade position", "cover position", "window opener position", "opening level", "currentpositionpercentage", "targetpositionpercentage")),
    AqaraCapabilityRule("locked", name_tokens=("door lock", "lock status", "deadbolt")),
    AqaraCapabilityRule("privacy_mode", name_tokens=("privacy mode", "privacy shield", "lens mask", "camera privacy")),
    AqaraCapabilityRule("recording_enabled", name_tokens=("recording", "record status", "record switch", "sd recording")),
    AqaraCapabilityRule("tamper_detected", name_tokens=("tamper", "forced entry", "pry alarm", "abnormal lock")),
    AqaraCapabilityRule("lock_jammed", name_tokens=("jam", "jammed", "lock jam")),
)

DEFAULT_COMMAND_RULES: tuple[AqaraCommandRule, ...] = (
    AqaraCommandRule(capability="switch_on", commands={"turn_on": "1", "turn_off": "0"}),
    AqaraCommandRule(
        capability="brightness_percent",
        dynamic_command="set_brightness",
        default_minimum=0,
        default_maximum=100,
    ),
    AqaraCommandRule(
        capability="cover_position",
        commands={"open": "100", "close": "0"},
        dynamic_command="set_position",
        argument="position",
        default_minimum=0,
        default_maximum=100,
    ),
    AqaraCommandRule(
        capability="color_temperature",
        dynamic_command="set_color_temperature",
        require_resource_bounds=True,
    ),
    AqaraCommandRule(
        capability="hue_degrees",
        dynamic_command="set_hue",
        default_minimum=0,
        default_maximum=360,
    ),
    AqaraCommandRule(
        capability="saturation_percent",
        dynamic_command="set_saturation",
        default_minimum=0,
        default_maximum=100,
    ),
    AqaraCommandRule(
        capability="target_temperature_c",
        dynamic_command="set_temperature",
        argument="temperature_c",
        require_resource_bounds=True,
        whole_number=False,
    ),
    AqaraCommandRule(
        capability="fan_speed_percent",
        dynamic_command="set_fan_speed",
        argument="speed",
        default_minimum=0,
        default_maximum=100,
    ),
)

MODEL_PROFILES: tuple[AqaraModelProfile, ...] = (
    AqaraModelProfile(
        model_prefixes=("lumi.plug.", "aqara.plug.", "lumi.switch.", "aqara.switch."),
        capability_rules=(
            AqaraCapabilityRule("switch_on", resource_ids=("4.1.85", "14.7.85", "4.1.111")),
            AqaraCapabilityRule("power_w", resource_ids=("8.0.2001",), name_tokens=("load power", "active power", "real power")),
            AqaraCapabilityRule("energy_kwh", resource_ids=("8.0.2002", "8.0.2003"), name_tokens=("power consumption", "energy")),
            AqaraCapabilityRule("voltage_v", resource_ids=("8.0.2004",), name_tokens=("voltage", "line voltage", "input voltage")),
            AqaraCapabilityRule("current_a", resource_ids=("8.0.2005",), name_tokens=("load current", "electric current", "ampere", "amps")),
            AqaraCapabilityRule("frequency_hz", resource_ids=("8.0.2006",), name_tokens=("frequency", "line frequency", "grid frequency")),
            AqaraCapabilityRule("power_factor", resource_ids=("8.0.2007",), name_tokens=("power factor",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("lumi.curtain.", "aqara.curtain.", "lumi.pusher.", "aqara.pusher."),
        capability_rules=(
            AqaraCapabilityRule("cover_position", resource_ids=("1.1.85", "14.1.85", "14.2.85", "14.7.111"), name_tokens=("currentpositionpercentage", "targetpositionpercentage")),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.lock.", "lumi.lock."),
        capability_rules=(
            AqaraCapabilityRule("locked", resource_ids=("6.1.85",), name_tokens=("door lock", "lock status", "deadbolt", "locked state")),
            AqaraCapabilityRule("battery_low", name_tokens=("low battery", "battery low", "low power alarm", "battery alarm")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
            AqaraCapabilityRule("contact_open", resource_ids=("3.1.185",), name_tokens=("door", "contact")),
            AqaraCapabilityRule("tamper_detected", name_tokens=("tamper", "forced entry", "pry alarm", "abnormal lock")),
            AqaraCapabilityRule("lock_jammed", name_tokens=("jam", "jammed", "lock jam")),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("lumi.sensor_ht.", "aqara.sensor_ht.", "lumi.weather.", "aqara.climate."),
        capability_rules=(
            AqaraCapabilityRule("temperature_c", name_tokens=("temperature",)),
            AqaraCapabilityRule("humidity_percent", name_tokens=("humidity",)),
            AqaraCapabilityRule("pressure_hpa", name_tokens=("pressure",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("lumi.motion.", "aqara.motion.", "lumi.sensor_occupy.", "aqara.sensor_occupy.", "aqara.presence."),
        capability_rules=(
            AqaraCapabilityRule("presence_detected", resource_ids=("2.1.85", "2.2.85"), name_tokens=("presence", "occupancy")),
            AqaraCapabilityRule("motion_detected", resource_ids=("2.1.85", "2.2.85"), name_tokens=("motion", "movement", "pir")),
            AqaraCapabilityRule("illuminance_lux", name_tokens=("lux", "illuminance", "light level")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("lumi.sensor_magnet.", "aqara.sensor_magnet.", "aqara.contact."),
        capability_rules=(
            AqaraCapabilityRule("contact_open", resource_ids=("3.1.85", "3.1.185"), name_tokens=("contact", "door", "window")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.water.", "lumi.sensor_wleak.", "lumi.flood."),
        capability_rules=(
            AqaraCapabilityRule("leak_detected", resource_ids=("3.2.85",), name_tokens=("water leak", "leak", "flood")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.smoke.", "lumi.smoke.", "aqara.gas.", "lumi.gas."),
        capability_rules=(
            AqaraCapabilityRule("smoke_alarm", resource_ids=("3.3.85",), name_tokens=("smoke",)),
            AqaraCapabilityRule("gas_alarm", resource_ids=("3.4.85",), name_tokens=("gas", "natural gas", "co alarm")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.airmonitor.", "lumi.airmonitor.", "aqara.tvoc.", "lumi.air.", "aqara.climate."),
        capability_rules=(
            AqaraCapabilityRule("temperature_c", resource_ids=("0.1.85",), name_tokens=("temperature",)),
            AqaraCapabilityRule("humidity_percent", resource_ids=("0.2.85",), name_tokens=("humidity",)),
            AqaraCapabilityRule("co2_ppm", resource_ids=("0.5.85",), name_tokens=("co2",)),
            AqaraCapabilityRule("voc_ppb", resource_ids=("0.6.85",), name_tokens=("tvoc", "voc")),
            AqaraCapabilityRule("pm25_ugm3", resource_ids=("0.7.85",), name_tokens=("pm2.5", "pm25")),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.light.", "lumi.light.", "aqara.bulb.", "lumi.bulb."),
        capability_rules=(
            AqaraCapabilityRule("switch_on", resource_ids=("4.1.85", "14.7.85", "4.1.111"), name_tokens=("light switch", "on/off", "onoff", "power switch")),
            AqaraCapabilityRule("brightness_percent", resource_ids=("5.1.85",), name_tokens=("brightness", "dimmer", "currentlevel")),
            AqaraCapabilityRule("color_temperature", name_tokens=("color temperature", "colour temperature", "colortemperature")),
            AqaraCapabilityRule("hue_degrees", name_tokens=("hue", "hue angle")),
            AqaraCapabilityRule("saturation_percent", name_tokens=("saturation", "colour saturation", "color saturation")),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.thermostat.", "lumi.thermostat.", "aqara.radiator.", "lumi.airrtc."),
        capability_rules=(
            AqaraCapabilityRule("temperature_c", name_tokens=("current temperature", "room temperature", "temperature value")),
            AqaraCapabilityRule("target_temperature_c", name_tokens=("set temperature", "settemperature", "target temperature", "heating temperature", "cooling temperature")),
            AqaraCapabilityRule("humidity_percent", name_tokens=("humidity",)),
            AqaraCapabilityRule("battery_percent", resource_ids=("8.0.2008",), name_tokens=("battery",)),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.fan.", "lumi.fan.", "aqara.airpurifier.", "lumi.airpurifier."),
        capability_rules=(
            AqaraCapabilityRule("switch_on", resource_ids=("4.1.85", "14.7.85", "4.1.111"), name_tokens=("on/off", "onoff", "power switch")),
            AqaraCapabilityRule("fan_speed_percent", name_tokens=("fan speed", "fanspeed", "fan level", "air speed")),
            AqaraCapabilityRule("filter_life_percent", name_tokens=("filter remaining life", "filter life")),
            AqaraCapabilityRule("pm25_ugm3", name_tokens=("pm2.5", "pm25")),
        ),
    ),
    AqaraModelProfile(
        model_prefixes=("aqara.camera.", "lumi.camera.", "aqara.doorbell.", "lumi.doorbell."),
        capability_rules=(
            AqaraCapabilityRule("motion_detected", name_tokens=("motion", "movement", "camera event")),
            AqaraCapabilityRule("person_detected", name_tokens=("person detected", "human detected", "face detected")),
            AqaraCapabilityRule("audio_detected", name_tokens=("sound detected", "audio detected", "cry detected", "sound alarm")),
            AqaraCapabilityRule("doorbell_pressed", name_tokens=("doorbell ring", "doorbell button", "bell press", "visitor call")),
            AqaraCapabilityRule("privacy_mode", name_tokens=("privacy mode", "privacy shield", "lens mask", "sleep mode")),
            AqaraCapabilityRule("recording_enabled", name_tokens=("recording", "record status", "record switch", "sd recording")),
            AqaraCapabilityRule("battery_low", name_tokens=("low battery", "battery low", "low power alarm", "battery alarm")),
        ),
    ),
)


def _resource_text(resource: AqaraResourceInfo) -> str:
    return " ".join(
        part.strip().lower()
        for part in (resource.name, resource.description or "", resource.resource_id)
        if str(part).strip()
    )


def _normalized_enum_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def enum_values_for_resource(resource: AqaraResourceInfo) -> dict[str, str]:
    raw = str(resource.enums or "").strip()
    if not raw:
        return {}
    pairs: list[tuple[str, str]] = []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        decoded = None
    if isinstance(decoded, dict):
        for left, right in decoded.items():
            left_text, right_text = str(left).strip(), str(right).strip()
            if left_text and right_text:
                if left_text.lstrip("-+").isdigit() and not right_text.lstrip("-+").isdigit():
                    pairs.append((right_text, left_text))
                else:
                    pairs.append((left_text, right_text))
    elif isinstance(decoded, list):
        for item in decoded:
            if not isinstance(item, dict):
                continue
            label = str(item.get("key") or item.get("label") or item.get("name") or "").strip()
            raw_value = item.get("value") if item.get("value") is not None else item.get("id")
            value = str(raw_value).strip() if raw_value is not None else ""
            if label and value:
                pairs.append((label, value))
    else:
        for item in re.split(r"[,;|]", raw):
            match = re.match(r"^\s*([^:=]+?)\s*[:=]\s*([^:=]+?)\s*$", item)
            if not match:
                continue
            left, right = match.group(1).strip(), match.group(2).strip()
            if left.lstrip("-+").isdigit() and not right.lstrip("-+").isdigit():
                pairs.append((right, left))
            else:
                pairs.append((left, right))
    values: dict[str, str] = {}
    for label, value in pairs:
        normalized = _normalized_enum_label(label)
        if normalized and normalized not in values and value not in values.values():
            values[normalized] = value
    return values


def capability_for_resource(*, model: str, resource: AqaraResourceInfo) -> str | None:
    text = _resource_text(resource)
    for profile in MODEL_PROFILES:
        if not profile.matches(model):
            continue
        for rule in profile.capability_rules:
            if resource.resource_id in rule.resource_ids:
                return rule.capability
            if any(token in text for token in rule.name_tokens):
                return rule.capability
    for rule in DEFAULT_CAPABILITY_RULES:
        if resource.resource_id in rule.resource_ids:
            return rule.capability
        if any(token in text for token in rule.name_tokens):
            return rule.capability
    return None


def command_bindings_for_capabilities(
    *,
    model: str,
    resource_map: dict[str, AqaraResourceInfo],
    capability_bindings: dict[str, str],
) -> dict[str, dict[str, str | bool | int]]:
    rules = list(DEFAULT_COMMAND_RULES)
    for profile in MODEL_PROFILES:
        if profile.matches(model):
            rules.extend(profile.command_rules)

    bindings: dict[str, dict[str, str | bool | int]] = {}
    for rule in rules:
        resource_id = capability_bindings.get(rule.capability)
        resource = resource_map.get(resource_id or "")
        if resource is None or not resource.is_writable:
            resource = next(
                (
                    candidate
                    for candidate in sorted(resource_map.values(), key=lambda item: item.resource_id)
                    if candidate.is_writable
                    and capability_for_resource(model=model, resource=candidate) == rule.capability
                ),
                None,
            )
        if resource is None:
            continue
        resource_id = resource.resource_id
        for command_id, value in rule.commands.items():
            bindings[command_id] = {"resource_id": resource_id, "value": value}
        if rule.dynamic_command:
            if rule.require_resource_bounds and (resource.min_value is None or resource.max_value is None):
                continue
            minimum = resource.min_value if resource.min_value is not None else rule.default_minimum
            maximum = resource.max_value if resource.max_value is not None else rule.default_maximum
            if minimum is None or maximum is None:
                continue
            if rule.default_minimum is not None:
                minimum = max(minimum, rule.default_minimum)
            if rule.default_maximum is not None:
                maximum = min(maximum, rule.default_maximum)
            if minimum <= maximum:
                bindings[rule.dynamic_command] = {
                    "resource_id": resource_id,
                    "dynamic": True,
                    "argument": rule.argument,
                    "min_value": minimum,
                    "max_value": maximum,
                    "whole_number": rule.whole_number,
                }
    normalized_model = str(model or "").strip().lower()
    if any(token in normalized_model for token in ("curtain", "shade", "cover", "pusher")):
        for resource in sorted(resource_map.values(), key=lambda item: item.resource_id):
            if not resource.is_writable:
                continue
            text = _resource_text(resource)
            if not any(token in text for token in ("motor control", "curtain control", "cover control", "motor command")):
                continue
            enum_values = enum_values_for_resource(resource)
            stop_value = next((enum_values[label] for label in ("stop", "pause", "hold") if label in enum_values), None)
            if stop_value is not None:
                bindings["stop_cover"] = {"resource_id": resource.resource_id, "value": stop_value}
                break
    return bindings
