from __future__ import annotations

import glob
import platform
from pathlib import Path
from typing import Iterable

from serial.tools import list_ports

from .bridge_models import AdapterCandidate


def discover_adapters() -> list[AdapterCandidate]:
    candidates = [_candidate_from_port(port) for port in list_ports.comports()]
    candidates.extend(_linux_stable_symlink_candidates(candidates))
    unique = _dedupe_candidates(candidates)
    return sorted(unique, key=lambda item: (-item.confidence, not item.stable, item.display_name.lower()))


def _candidate_from_port(port) -> AdapterCandidate:
    path = str(port.device)
    description = str(port.description or path)
    manufacturer = _clean(port.manufacturer)
    product = _clean(port.product) or description
    serial_number = _clean(port.serial_number)
    adapter_hint, confidence = infer_adapter_hint(
        " ".join(
            token
            for token in [
                path,
                description,
                manufacturer,
                product,
                serial_number,
                getattr(port, "hwid", None),
            ]
            if token
        )
    )
    stable = _is_stable_path(path)
    if stable:
        confidence = min(1.0, confidence + 0.08)
    return AdapterCandidate(
        id=_adapter_id(path, serial_number),
        path=path,
        display_name=_display_name(product=product, manufacturer=manufacturer, path=path),
        adapter_hint=adapter_hint,
        confidence=confidence,
        stable=stable,
        source="pyserial",
        manufacturer=manufacturer,
        product=product,
        serial_number=serial_number,
        vid=getattr(port, "vid", None),
        pid=getattr(port, "pid", None),
        metadata={"hwid": _clean(getattr(port, "hwid", None)), "system": platform.system()},
    )


def infer_adapter_hint(text: str) -> tuple[str | None, float]:
    normalized = text.lower()
    rules: list[tuple[tuple[str, ...], str, float]] = [
        (("zbdongle-e", "dongle-e", "sonoff dongle-e"), "ember", 0.94),
        (("zbdongle-p", "cc2652", "cc1352", "cc2531", "slae.sh cc2652", "tube_zb cc2652"), "zstack", 0.92),
        (("sonoff zigbee 3.0 usb dongle plus", "itead sonoff zigbee 3.0 usb dongle plus"), "zstack", 0.88),
        (("zbdongle-e", "skyconnect", "home assistant connect zbt-1", "efr32", "mgm21", "ember"), "ember", 0.9),
        (("conbee", "raspbee", "dresden elektronik"), "deconz", 0.86),
        (("zigate",), "zigate", 0.86),
        (("zboss",), "zboss", 0.82),
        (("slzb-06", "smlight"), "zstack", 0.72),
        (("ch340", "cp210", "ft232", "usb serial", "usb-serial"), None, 0.48),
    ]
    for needles, adapter, confidence in rules:
        if any(needle in normalized for needle in needles):
            return adapter, confidence
    return None, 0.35 if normalized.strip() else 0.1


def _linux_stable_symlink_candidates(existing: Iterable[AdapterCandidate]) -> list[AdapterCandidate]:
    if platform.system().lower() != "linux":
        return []
    existing_by_target = {str(Path(candidate.path).resolve()): candidate for candidate in existing}
    candidates: list[AdapterCandidate] = []
    for pattern, source in (
        ("/dev/serial/by-id/*", "udev-by-id"),
        ("/dev/serial/by-path/*", "udev-by-path"),
    ):
        for symlink in glob.glob(pattern):
            target = str(Path(symlink).resolve())
            base = existing_by_target.get(target)
            hint, confidence = infer_adapter_hint(symlink)
            candidates.append(
                AdapterCandidate(
                    id=_adapter_id(symlink, base.serial_number if base else None),
                    path=symlink,
                    display_name=base.display_name if base else Path(symlink).name,
                    adapter_hint=base.adapter_hint or hint if base else hint,
                    confidence=min(1.0, max(base.confidence if base else 0.0, confidence) + 0.12),
                    stable=True,
                    source=source,
                    manufacturer=base.manufacturer if base else None,
                    product=base.product if base else None,
                    serial_number=base.serial_number if base else None,
                    vid=base.vid if base else None,
                    pid=base.pid if base else None,
                    metadata={"target": target},
                )
            )
    return candidates


def _dedupe_candidates(candidates: Iterable[AdapterCandidate]) -> list[AdapterCandidate]:
    best: dict[str, AdapterCandidate] = {}
    for candidate in candidates:
        key = str(Path(candidate.path).resolve()) if candidate.path.startswith("/") else candidate.path.upper()
        current = best.get(key)
        if current is None or _score(candidate) > _score(current):
            best[key] = candidate
    return list(best.values())


def _score(candidate: AdapterCandidate) -> tuple[float, bool]:
    return candidate.confidence, candidate.stable


def _is_stable_path(path: str) -> bool:
    return path.startswith("/dev/serial/by-id/") or path.startswith("/dev/serial/by-path/")


def _display_name(*, product: str | None, manufacturer: str | None, path: str) -> str:
    if product and manufacturer and manufacturer.lower() not in product.lower():
        return f"{manufacturer} {product}"
    return product or manufacturer or path


def _adapter_id(path: str, serial_number: str | None) -> str:
    token = serial_number or Path(path).name or path
    return token.replace(" ", "_").replace("/", "_")


def _clean(value) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None
