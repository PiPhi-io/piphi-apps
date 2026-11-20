from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from piphi_runtime_kit_python import SourceTelemetryPoint

from .persistence import CycleState
from .schemas import DeviceConfig


def _seconds(start: str, finish: str) -> float:
    return max(
        0.0, (datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds()
    )


def apply_points(
    original: CycleState,
    points: list[SourceTelemetryPoint],
    config: DeviceConfig,
    *,
    already_processed: set[str],
) -> tuple[CycleState, list[str], list[tuple[str, dict[str, Any]]]]:
    state = deepcopy(original)
    accepted: list[str] = []
    events: list[tuple[str, dict[str, Any]]] = []
    for point in points:
        if point.event_id in already_processed or point.event_id in accepted:
            continue
        accepted.append(point.event_id)
        if (
            point.metric != config.power_metric
            or point.value_kind != "number"
            or not isinstance(point.value, int | float)
        ):
            continue
        power = float(point.value)
        observed_at = point.collected_at.isoformat()
        if (
            state.last_sample_at is not None
            and state.last_sample_power_w is not None
            and state.cycle_active
        ):
            elapsed = min(
                _seconds(state.last_sample_at, observed_at), float(config.max_sample_gap_seconds)
            )
            state.cycle_energy_kwh += (
                ((state.last_sample_power_w + power) / 2.0) * elapsed / 3_600_000.0
            )
        state.power_w = power
        state.last_sample_at = observed_at
        state.last_sample_power_w = power

        if not state.cycle_active:
            if power >= config.start_threshold_w:
                if state.start_candidate_count == 0:
                    state.start_candidate_at = observed_at
                state.start_candidate_count += 1
                if state.start_candidate_count >= config.start_debounce_samples:
                    state.cycle_state = "running"
                    state.cycle_started_at = state.start_candidate_at or observed_at
                    state.cycle_finished_at = None
                    state.cycle_duration_s = None
                    state.cycle_energy_kwh = 0.0
                    state.peak_power_w = power
                    state.start_candidate_count = 0
                    state.start_candidate_at = None
                    events.append(
                        ("cycle.started", {"started_at": state.cycle_started_at, "power_w": power})
                    )
            else:
                state.start_candidate_count = 0
                state.start_candidate_at = None
        else:
            state.peak_power_w = max(state.peak_power_w or power, power)
            if power <= config.stop_threshold_w:
                state.stop_candidate_count += 1
                if state.stop_candidate_count >= config.stop_debounce_samples:
                    state.cycle_state = "idle"
                    state.cycle_finished_at = observed_at
                    state.cycle_duration_s = _seconds(
                        state.cycle_started_at or observed_at, observed_at
                    )
                    state.lifetime_cycle_count += 1
                    state.stop_candidate_count = 0
                    events.append(
                        (
                            "cycle.finished",
                            {
                                "finished_at": observed_at,
                                "duration_s": state.cycle_duration_s,
                                "energy_kwh": state.cycle_energy_kwh,
                            },
                        )
                    )
            else:
                state.stop_candidate_count = 0
    return state, accepted, events
