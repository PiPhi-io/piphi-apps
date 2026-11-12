from __future__ import annotations

import asyncio
import inspect
import ipaddress
import os
import socket
import struct
from typing import Any

from kasa import Credentials, Device, Discover

_DIRECT_CONNECT_TIMEOUT = 10
_DISCOVERY_TIMEOUT = 8
_DISCOVERY_PACKETS = 5
_DISCOVERY_TARGETS_ENV = "PIPHI_TP_LINK_DISCOVERY_TARGETS"
_DEVICE_CONFIG_CACHE: dict[str, Any] = {}


def _linux_interface_networks() -> list[ipaddress.IPv4Network]:
    """Return usable private IPv4 networks without depending on OS tools."""
    try:
        import fcntl
    except ImportError:
        return []

    networks: set[ipaddress.IPv4Network] = set()
    ignored_prefixes = (
        "br-",
        "docker",
        "lo",
        "tailscale",
        "tap",
        "tun",
        "veth",
        "virbr",
        "wg",
    )
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        return []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        for _, interface in interfaces:
            if interface.lower().startswith(ignored_prefixes):
                continue
            request = struct.pack("256s", interface.encode("utf-8")[:15])
            try:
                address = socket.inet_ntoa(
                    fcntl.ioctl(probe.fileno(), 0x8915, request)[20:24]
                )
                netmask = socket.inet_ntoa(
                    fcntl.ioctl(probe.fileno(), 0x891B, request)[20:24]
                )
                network = ipaddress.ip_network(f"{address}/{netmask}", strict=False)
            except (OSError, ValueError):
                continue
            if network.is_private and network.prefixlen < 31:
                networks.add(network)

    return sorted(
        networks,
        key=lambda network: (int(network.network_address), network.prefixlen),
    )


def _discovery_targets() -> list[str]:
    """Choose LAN-specific broadcasts so VPN/default routes cannot swallow discovery."""
    configured = [
        value.strip()
        for value in os.getenv(_DISCOVERY_TARGETS_ENV, "").split(",")
        if value.strip()
    ]
    if configured:
        return list(dict.fromkeys(configured))

    targets = [
        str(network.broadcast_address) for network in _linux_interface_networks()
    ]
    return list(dict.fromkeys(targets)) or ["255.255.255.255"]


def _safe_feature_value(value: Any) -> Any:
    try:
        if callable(value):
            return value()
        return value
    except Exception:
        return None


def _safe_enum_like(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value"):
        return getattr(value, "value")
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", "")
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _normalize_feature(feature_id: str, feature: Any) -> dict[str, Any]:
    feature_type = _safe_enum_like(getattr(feature, "type", None)) or "unknown"
    category = _safe_enum_like(getattr(feature, "category", None))
    writable = bool(getattr(feature, "attribute_setter", None))

    return {
        "id": feature_id,
        "name": str(getattr(feature, "name", feature_id)),
        "type": str(feature_type),
        "category": category,
        "value": _safe_feature_value(getattr(feature, "value", None)),
        "unit": _safe_feature_value(getattr(feature, "unit", None)),
        "choices": _safe_feature_value(getattr(feature, "choices", None)),
        "range": _safe_feature_value(getattr(feature, "range", None)),
        "writable": writable,
    }


def _extract_features(device: Any) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    try:
        for key, feature in device.features.items():
            features[key] = _normalize_feature(key, feature)
    except Exception:
        features = {}
    return features


def _match_feature(
    features: dict[str, dict[str, Any]],
    *,
    id_tokens: list[str],
    name_tokens: list[str] | None = None,
) -> tuple[float | None, str | None]:
    name_tokens = name_tokens or []
    for feature in features.values():
        fid = str(feature.get("id", "")).lower()
        fname = str(feature.get("name", "")).lower()
        if any(token in fid for token in id_tokens) or any(
            token in fname for token in name_tokens
        ):
            value = _to_float(feature.get("value"))
            if value is not None:
                return value, str(feature.get("unit", "") or "")
    return None, None


def _extract_energy_metrics(features: dict[str, dict[str, Any]]) -> dict[str, float]:
    power_value, power_unit = _match_feature(
        features,
        id_tokens=[
            "power",
            "current_power",
            "emeter_power",
            "current_consumption",
        ],
        name_tokens=["power", "current consumption"],
    )
    today_value, today_unit = _match_feature(
        features,
        id_tokens=["today", "daily", "day_energy", "consumption_today"],
        name_tokens=["today", "daily"],
    )
    month_value, month_unit = _match_feature(
        features,
        id_tokens=["month", "monthly", "this_month", "consumption_month"],
        name_tokens=["month", "monthly"],
    )

    metrics: dict[str, float] = {}

    if power_value is not None:
        unit = (power_unit or "").strip().lower()
        if unit == "mw":
            metrics["current_power_w"] = power_value / 1000.0
        else:
            metrics["current_power_w"] = power_value

    if today_value is not None:
        unit = (today_unit or "").strip().lower()
        if unit == "wh":
            metrics["today_kwh"] = today_value / 1000.0
        else:
            metrics["today_kwh"] = today_value

    if month_value is not None:
        unit = (month_unit or "").strip().lower()
        if unit == "wh":
            metrics["month_kwh"] = month_value / 1000.0
        else:
            metrics["month_kwh"] = month_value

    return metrics


def _derive_capabilities_from_features(
    features: dict[str, dict[str, Any]],
) -> list[str]:
    capabilities: set[str] = set()

    if "state" in features:
        capabilities.add("switch")

    for feature in features.values():
        feature_id = str(feature.get("id", "")).lower()
        feature_type = str(feature.get("type", "")).lower()
        unit = str(feature.get("unit", "")).lower()

        if "brightness" in feature_id or "dimming" in feature_id:
            capabilities.add("brightness")
        if "color_temp" in feature_id or "color temperature" in feature_id:
            capabilities.add("color_temperature")
        if "hsv" in feature_id or feature_id in {"hue", "saturation", "color"}:
            capabilities.add("color")
        if "power" in feature_id and "w" in unit:
            capabilities.add("power")
        if "today" in feature_id or "daily" in feature_id or "day_energy" in feature_id:
            capabilities.add("energy_today")
        if (
            "month" in feature_id
            or "monthly" in feature_id
            or "consumption_month" in feature_id
        ):
            capabilities.add("energy_this_month")
        if "temperature" in feature_id:
            capabilities.add("temperature")
        if "humidity" in feature_id:
            capabilities.add("humidity")
        if feature_type in {"number", "sensor", "binary_sensor"}:
            capabilities.add("telemetry")

    if "current_power_w" in _extract_energy_metrics(features):
        capabilities.add("energy_power")

    capabilities.add("refresh")
    return sorted(capabilities)


async def _disconnect_device(device: Any) -> None:
    try:
        disconnect = getattr(device, "disconnect", None)
        if callable(disconnect):
            result = disconnect()
            if inspect.isawaitable(result):
                await result
            return

        protocol = getattr(device, "protocol", None)
        close = getattr(protocol, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
    except Exception:
        return


def _command_args_for_child(has_children: bool, args: list[str]) -> list[str]:
    if has_children:
        return ["child_id", *args]
    return args


def _has_writable_feature(
    features: dict[str, dict[str, Any]], candidates: list[str]
) -> bool:
    for candidate in candidates:
        feature = features.get(candidate)
        if feature and feature.get("writable"):
            return True
    return False


def _build_supported_commands(
    device: Any, features: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    has_children = bool(getattr(device, "children", []))
    common_args = _command_args_for_child(has_children, [])

    commands: list[dict[str, Any]] = [
        {"id": "refresh", "label": "Refresh", "args": common_args},
        {"id": "read_energy", "label": "Read Energy", "args": common_args},
    ]

    if hasattr(device, "turn_on"):
        commands.append(
            {
                "id": "turn_on",
                "label": "Turn On",
                "args": _command_args_for_child(has_children, []),
            }
        )
    if hasattr(device, "turn_off"):
        commands.append(
            {
                "id": "turn_off",
                "label": "Turn Off",
                "args": _command_args_for_child(has_children, []),
            }
        )
    if hasattr(device, "turn_on") and hasattr(device, "turn_off"):
        commands.append(
            {
                "id": "toggle",
                "label": "Toggle Power",
                "args": _command_args_for_child(has_children, []),
            }
        )

    if hasattr(device, "set_alias"):
        commands.append(
            {
                "id": "set_alias",
                "label": "Set Alias",
                "args": _command_args_for_child(has_children, ["alias"]),
            }
        )

    if hasattr(device, "reboot"):
        commands.append(
            {
                "id": "reboot",
                "label": "Reboot Device",
                "args": _command_args_for_child(has_children, ["delay"]),
            }
        )

    writable_features = [
        feature for feature in features.values() if feature.get("writable")
    ]
    if writable_features:
        commands.append(
            {
                "id": "set_feature",
                "label": "Set Feature",
                "args": _command_args_for_child(has_children, ["feature_id", "value"]),
                "writable_features": [feature["id"] for feature in writable_features],
            }
        )
        commands.append(
            {
                "id": "feature_action",
                "label": "Feature Action",
                "args": _command_args_for_child(has_children, ["feature_id", "value"]),
                "writable_features": [feature["id"] for feature in writable_features],
            }
        )

    if _has_writable_feature(features, ["brightness", "dimming_level"]):
        commands.append(
            {
                "id": "set_brightness",
                "label": "Set Brightness",
                "args": _command_args_for_child(has_children, ["brightness"]),
            }
        )

    if _has_writable_feature(features, ["color_temperature", "color_temp"]):
        commands.append(
            {
                "id": "set_color_temperature",
                "label": "Set Color Temperature",
                "args": _command_args_for_child(has_children, ["kelvin"]),
            }
        )

    if _has_writable_feature(features, ["hue", "saturation"]):
        commands.append(
            {
                "id": "set_hue_saturation",
                "label": "Set Hue/Saturation",
                "args": _command_args_for_child(has_children, ["hue", "saturation"]),
            }
        )

    return commands


def _build_credentials(
    username: str | None = None, password: str | None = None
) -> Credentials | None:
    if username and password:
        return Credentials(username=username, password=password)
    return None


def _cache_device_config(host: str, device: Any) -> None:
    config = getattr(device, "config", None)
    if config is not None:
        _DEVICE_CONFIG_CACHE[host] = config


async def _resolve_device(
    host: str, username: str | None = None, password: str | None = None
) -> Any:
    credentials = _build_credentials(username=username, password=password)
    cached_config = _DEVICE_CONFIG_CACHE.get(host)

    if cached_config is not None:
        try:
            return await Device.connect(config=cached_config)
        except Exception:
            _DEVICE_CONFIG_CACHE.pop(host, None)

    device = await Discover.try_connect_all(
        host,
        timeout=_DIRECT_CONNECT_TIMEOUT,
        credentials=credentials,
    )
    if device is not None:
        _cache_device_config(host, device)
        return device

    device = await Discover.discover_single(
        host,
        discovery_timeout=_DIRECT_CONNECT_TIMEOUT,
        credentials=credentials,
    )
    if device is None:
        raise RuntimeError(f"Unable to connect to Kasa device at host '{host}'")
    try:
        await device.update()
        _cache_device_config(host, device)
    except Exception:
        await _disconnect_device(device)
        raise
    return device


def _resolve_command_target(device: Any, args: dict[str, Any]) -> Any:
    child_id = str(args.get("child_id") or "").strip()
    if not child_id:
        return device

    child = device.get_child_device(child_id)
    if child is None:
        available = [
            str(getattr(child_device, "device_id", "")).strip()
            or str(getattr(child_device, "alias", ""))
            for child_device in getattr(device, "children", [])
        ]
        raise RuntimeError(
            f"Child '{child_id}' not found. Available children: {', '.join([v for v in available if v])}"
        )
    return child


def _resolve_writable_feature(
    target: Any, feature_id: str, candidates: list[str] | None = None
) -> Any:
    if feature_id:
        feature = target.features.get(feature_id)
        if feature is None:
            raise RuntimeError(
                f"Feature '{feature_id}' not found. Available: {', '.join(target.features.keys())}"
            )
        if not getattr(feature, "attribute_setter", None):
            raise RuntimeError(f"Feature '{feature_id}' is read-only")
        return feature

    candidates = candidates or []
    for candidate in candidates:
        feature = target.features.get(candidate)
        if feature and getattr(feature, "attribute_setter", None):
            return feature

    raise RuntimeError(
        "No writable feature matched candidates: " + ", ".join(candidates)
    )


def _to_int(value: Any, arg_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid integer for '{arg_name}': {value}") from exc


def _serialize_child(child: Any) -> dict[str, Any]:
    child_features = _extract_features(child)
    child_energy = _extract_energy_metrics(child_features)
    return {
        "id": str(getattr(child, "device_id", "") or getattr(child, "alias", "")),
        "alias": getattr(child, "alias", None),
        "model": getattr(child, "model", None),
        "is_on": bool(getattr(child, "is_on", False)),
        "features": child_features,
        "energy": child_energy,
        "capabilities": _derive_capabilities_from_features(child_features),
        "supported_commands": _build_supported_commands(child, child_features),
    }


def _serialize_device(device: Any) -> dict[str, Any]:
    features = _extract_features(device)
    children = [_serialize_child(child) for child in getattr(device, "children", [])]
    energy = _extract_energy_metrics(features)

    signal = getattr(device, "rssi", None)
    if signal is None:
        signal = getattr(device, "signal_level", None)

    payload = {
        "host": device.host,
        "name": device.alias,
        "alias": device.alias,
        "model": device.model,
        "is_on": bool(getattr(device, "is_on", False)),
        "device_type": str(device.device_type),
        "mac": device.mac,
        "signal_strength": signal,
        "sys_info": device.sys_info,
        "features": features,
        "energy": energy,
        "capabilities": _derive_capabilities_from_features(features),
        "commands": _build_supported_commands(device, features),
        "supported_commands": _build_supported_commands(device, features),
        "children": children,
    }

    if "current_power_w" in energy:
        payload["current_power_w"] = energy["current_power_w"]
    if "today_kwh" in energy:
        payload["today_kwh"] = energy["today_kwh"]
    if "month_kwh" in energy:
        payload["month_kwh"] = energy["month_kwh"]

    return payload


async def discover_devices(
    username: str | None = None,
    password: str | None = None,
    host: str | None = None,
) -> list[dict[str, Any]]:
    host = str(host or "").strip()
    if host:
        return [
            await fetch_device_state(host=host, username=username, password=password)
        ]

    targets = _discovery_targets()
    scan_results = await asyncio.gather(
        *(
            Discover.discover(
                target=target,
                discovery_timeout=_DISCOVERY_TIMEOUT,
                discovery_packets=_DISCOVERY_PACKETS,
                username=username,
                password=password,
            )
            for target in targets
        ),
        return_exceptions=True,
    )

    found: dict[str, Any] = {}
    scan_failures: list[str] = []
    for target, result in zip(targets, scan_results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, Exception):
            scan_failures.append(f"{target}: {result}")
            continue
        for discovered_host, device in result.items():
            if discovered_host in found:
                await _disconnect_device(device)
                continue
            found[discovered_host] = device

    if not found and len(scan_failures) == len(targets):
        details = "; ".join(scan_failures)
        raise RuntimeError(
            f"Network scan failed ({details}). Try entering the device IP address "
            "or hostname for targeted discovery."
        )

    devices: list[dict[str, Any]] = []
    failures: list[str] = []

    for discovered_host, device in found.items():
        try:
            # Some python-kasa transports return a connected device whose
            # feature data is still lazy. Refresh before serialization so a
            # valid discovery result is not rejected as unreadable.
            await device.update()
            resolved_host = str(
                getattr(device, "host", "") or discovered_host
            ).strip()
            _cache_device_config(resolved_host, device)
            devices.append(_serialize_device(device))
        except Exception as exc:
            host_hint = str(getattr(device, "host", "") or "unknown-host")
            failures.append(f"{host_hint}: {exc}")
        finally:
            await _disconnect_device(device)

    if not devices and failures:
        raise RuntimeError(
            "Discovered devices, but none could be read. "
            + "Try targeted discovery with the device IP address. "
            + "Failures: "
            + "; ".join(failures)
        )

    return devices


async def fetch_device_state(
    host: str, username: str | None = None, password: str | None = None
) -> dict[str, Any]:
    device = await _resolve_device(host=host, username=username, password=password)
    try:
        # A device may have changed outside PiPhi (for example, in the Kasa app)
        # after the connection object was created. Always refresh immediately
        # before serializing so automation conditions see the physical state.
        await device.update()
        _cache_device_config(host, device)
        return _serialize_device(device)
    finally:
        await _disconnect_device(device)


async def execute_device_command(
    *,
    host: str,
    command: str,
    args: dict[str, Any] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    args = args or {}
    device = await _resolve_device(host=host, username=username, password=password)
    try:
        # Commands such as toggle depend on the current state. Refresh first so
        # changes made by another controller are not mistaken for stale state.
        await device.update()
        target = _resolve_command_target(device, args)

        if command == "turn_on":
            if not hasattr(target, "turn_on"):
                raise RuntimeError("This device does not support turn_on")
            await target.turn_on()
        elif command == "turn_off":
            if not hasattr(target, "turn_off"):
                raise RuntimeError("This device does not support turn_off")
            await target.turn_off()
        elif command == "toggle":
            if not hasattr(target, "turn_on") or not hasattr(target, "turn_off"):
                raise RuntimeError("This device does not support toggle")
            if bool(getattr(target, "is_on", False)):
                await target.turn_off()
            else:
                await target.turn_on()
        elif command == "set_alias":
            alias = str(args.get("alias") or "").strip()
            if not alias:
                raise RuntimeError("Missing required arg 'alias'")
            if not hasattr(target, "set_alias"):
                raise RuntimeError("This device does not support set_alias")
            await target.set_alias(alias)
        elif command == "reboot":
            delay = _to_int(args.get("delay", 1), "delay")
            if not hasattr(target, "reboot"):
                raise RuntimeError("This device does not support reboot")
            await target.reboot(delay=delay)
        elif command in {"refresh", "read_energy"}:
            pass
        elif command == "set_feature":
            feature_id = str(args.get("feature_id") or "").strip()
            if not feature_id:
                raise RuntimeError("Missing required arg 'feature_id'")
            if "value" not in args:
                raise RuntimeError("Missing required arg 'value' for set_feature")

            feature = _resolve_writable_feature(target, feature_id=feature_id)
            await feature.set_value(args.get("value"))
        elif command in {"dynamic_feature", "feature_action"}:
            feature_id = str(args.get("feature_id") or "").strip()
            if not feature_id:
                raise RuntimeError("Missing required arg 'feature_id'")

            feature = _resolve_writable_feature(target, feature_id=feature_id)
            await feature.set_value(args.get("value", None))
        elif command == "set_brightness":
            feature = _resolve_writable_feature(
                target,
                feature_id="",
                candidates=["brightness", "dimming_level"],
            )
            brightness = args.get("brightness", args.get("value"))
            await feature.set_value(_to_int(brightness, "brightness"))
        elif command == "set_color_temperature":
            feature = _resolve_writable_feature(
                target,
                feature_id="",
                candidates=["color_temperature", "color_temp"],
            )
            kelvin = args.get("kelvin", args.get("value"))
            await feature.set_value(_to_int(kelvin, "kelvin"))
        elif command == "set_hue_saturation":
            hue_feature = _resolve_writable_feature(
                target, feature_id="", candidates=["hue"]
            )
            sat_feature = _resolve_writable_feature(
                target, feature_id="", candidates=["saturation"]
            )
            await hue_feature.set_value(_to_int(args.get("hue"), "hue"))
            await sat_feature.set_value(_to_int(args.get("saturation"), "saturation"))
        else:
            raise RuntimeError(f"Unsupported command '{command}'")

        await device.update()
        return _serialize_device(device)
    finally:
        await _disconnect_device(device)
