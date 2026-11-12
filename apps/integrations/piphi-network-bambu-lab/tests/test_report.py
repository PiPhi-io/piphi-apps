from __future__ import annotations

from piphi_network_bambu_lab.report import normalize_print_report


def test_normalizes_full_status_without_leaking_job_metadata() -> None:
    result = normalize_print_report(
        {
            "print": {
                "command": "push_status",
                "gcode_state": "RUNNING",
                "mc_percent": 52,
                "mc_remaining_time": 34,
                "layer_num": 24,
                "total_layer_num": 90,
                "nozzle_temper": 220.5,
                "bed_temper": 60,
                "gcode_file": "private-project.3mf",
                "task_id": "account-specific-id",
                "ipcam": {"ipcam_dev": "1"},
            }
        }
    )
    assert result == {
        "print_status": "RUNNING",
        "print_progress_percent": 52.0,
        "remaining_time_minutes": 34.0,
        "current_layer": 24,
        "total_layers": 90,
        "nozzle_temperature_c": 220.5,
        "bed_temperature_c": 60.0,
        "connected": True,
    }


def test_p1_delta_preserves_previous_valid_fields() -> None:
    previous = {"print_status": "RUNNING", "print_progress_percent": 51.0, "connected": True}
    result = normalize_print_report(
        {"print": {"command": "push_status", "mc_percent": "52"}}, previous
    )
    assert result == {"print_status": "RUNNING", "print_progress_percent": 52.0, "connected": True}
    assert previous["print_progress_percent"] == 51.0


def test_rejects_unrelated_or_invalid_only_messages() -> None:
    assert normalize_print_report({"system": {"command": "ledctrl"}}) is None
    assert normalize_print_report({"print": {"command": "push_status", "mc_percent": 999}}) is None
    assert normalize_print_report({"print": {"command": "push_status", "bed_temper": "nan"}}) is None
    assert normalize_print_report({"print": {"command": "push_status", "mc_percent": True}}) is None
