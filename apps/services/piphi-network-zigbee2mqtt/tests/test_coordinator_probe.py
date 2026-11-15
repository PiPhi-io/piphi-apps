from __future__ import annotations

from piphi_network_zigbee2mqtt.coordinator_probe import probe_coordinator


def test_linux_probe_reports_process_holding_coordinator(tmp_path) -> None:
    device = tmp_path / "ttyUSB0"
    device.touch()
    proc = tmp_path / "proc"
    holder = proc / "4242"
    (holder / "fd").mkdir(parents=True)
    (holder / "comm").write_text("zigbee2mqtt\n", encoding="utf-8")
    (holder / "fd" / "7").symlink_to(device)

    result = probe_coordinator(str(device), proc_root=proc, system="Linux")

    assert result.available is False
    assert result.in_use is True
    assert result.exclusive_verified is True
    assert result.holders == ["pid:4242:zigbee2mqtt"]


def test_linux_probe_accepts_unopened_coordinator(tmp_path) -> None:
    device = tmp_path / "ttyUSB0"
    device.touch()
    proc = tmp_path / "proc"
    proc.mkdir()

    result = probe_coordinator(str(device), proc_root=proc, system="Linux")

    assert result.available is True
    assert result.in_use is False


def test_linux_probe_rejects_missing_coordinator(tmp_path) -> None:
    result = probe_coordinator(
        str(tmp_path / "missing"),
        proc_root=tmp_path / "proc",
        system="Linux",
    )

    assert result.available is False
    assert result.in_use is False
