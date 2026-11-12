from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pynmea2


CURRENT_FIX_MAX_AGE_MS = 15_000
STALE_FIX_MAX_AGE_MS = 180_000


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def normalize_fix_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"", "none", "invalid", "1"}:
        return "searching"
    if status == "3":
        return "3d"
    return status


def derive_fix_quality(status: str, satellites: int | None, hdop: float | None, signal: str) -> str:
    if signal == "stale":
        return "stale"
    if signal != "fixed":
        return "searching"
    if status in {"dgps", "rtk"}:
        return "excellent"
    if hdop is not None and hdop <= 1.5 and (satellites or 0) >= 6:
        return "strong"
    if hdop is not None and hdop <= 3 and (satellites or 0) >= 4:
        return "good"
    if (satellites or 0) >= 3:
        return "usable"
    return "weak"


@dataclass(slots=True)
class FixAccumulator:
    latitude: float | None = None
    longitude: float | None = None
    speed_knots: float | None = None
    satellites: int | None = None
    hdop: float | None = None
    altitude_meters: float | None = None
    fix_status: str = "searching"
    last_sentence_ms: int | None = None
    last_valid_ms: int | None = None
    last_good: dict[str, Any] | None = field(default=None)

    def ingest(self, sentence: str, *, now_ms: int | None = None) -> dict[str, Any]:
        now = now_ms if now_ms is not None else _now_ms()
        parsed = pynmea2.parse(sentence, check=False)
        self.last_sentence_ms = now
        kind = parsed.sentence_type.upper()
        if kind == "RMC":
            if getattr(parsed, "status", "") == "A":
                self.latitude = float(parsed.latitude)
                self.longitude = float(parsed.longitude)
                self.speed_knots = float(parsed.spd_over_grnd or 0)
                self.fix_status = "valid"
        elif kind == "GGA":
            self.satellites = int(parsed.num_sats) if parsed.num_sats else None
            self.hdop = float(parsed.horizontal_dil) if parsed.horizontal_dil else None
            quality = int(parsed.gps_qual or 0)
            if quality > 0:
                self.latitude = float(parsed.latitude)
                self.longitude = float(parsed.longitude)
                self.altitude_meters = float(parsed.altitude) if parsed.altitude else None
                self.fix_status = "dgps" if quality == 2 else "valid"
        elif kind == "GSA":
            self.hdop = float(parsed.hdop) if parsed.hdop else self.hdop
            self.fix_status = normalize_fix_status(getattr(parsed, "mode_fix_type", None))
        return self.snapshot(now_ms=now)

    def snapshot(self, *, now_ms: int | None = None) -> dict[str, Any]:
        now = now_ms if now_ms is not None else _now_ms()
        age = now - self.last_valid_ms if self.last_valid_ms is not None else None
        has_position = self.latitude is not None and self.longitude is not None
        if has_position and self.last_sentence_ms is not None and now - self.last_sentence_ms <= CURRENT_FIX_MAX_AGE_MS:
            signal = "fixed"
            self.last_valid_ms = self.last_sentence_ms
            age = max(0, now - self.last_valid_ms)
        elif self.last_good and age is not None and age <= STALE_FIX_MAX_AGE_MS:
            signal = "stale"
            self.latitude = self.last_good.get("latitude")
            self.longitude = self.last_good.get("longitude")
        else:
            signal = "searching"
        quality = derive_fix_quality(self.fix_status, self.satellites, self.hdop, signal)
        metrics = {
            "latitude": self.latitude if signal != "searching" else None,
            "longitude": self.longitude if signal != "searching" else None,
            "speed_knots": self.speed_knots if signal != "searching" else None,
            "satellites": self.satellites,
            "hdop": self.hdop,
            "altitude_meters": self.altitude_meters,
            "fix_status": self.fix_status,
            "fix_quality": quality,
            "position_source": "last_known" if signal == "stale" else ("live" if signal == "fixed" else "none"),
            "fix_age_ms": age,
        }
        if signal == "fixed":
            self.last_good = dict(metrics)
        return {"signal_state": signal, "stale": signal == "stale", "metrics": metrics}


def build_units(metrics: dict[str, Any]) -> dict[str, str]:
    units = {
        "latitude": "degrees",
        "longitude": "degrees",
        "speed_knots": "kn",
        "satellites": "count",
        "hdop": "ratio",
        "altitude_meters": "m",
        "fix_age_ms": "ms",
    }
    return {key: unit for key, unit in units.items() if metrics.get(key) is not None}
