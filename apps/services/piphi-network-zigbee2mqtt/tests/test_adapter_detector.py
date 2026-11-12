from __future__ import annotations

from piphi_network_zigbee2mqtt.adapter_detector import infer_adapter_hint


def test_infer_sonoff_zigbee_3_usb_dongle_plus_as_zstack() -> None:
    adapter, confidence = infer_adapter_hint("ITead Sonoff Zigbee 3.0 USB Dongle Plus")

    assert adapter == "zstack"
    assert confidence >= 0.8


def test_infer_sonoff_dongle_e_as_ember_before_generic_sonoff_rule() -> None:
    adapter, confidence = infer_adapter_hint("SONOFF Zigbee 3.0 USB Dongle Plus ZBDongle-E")

    assert adapter == "ember"
    assert confidence >= 0.9
