from piphi_network_sense.sense_client import SenseDeviceReading, _bucket_power


def test_realtime_bucket_power_falls_back_by_id_or_name() -> None:
    devices = (
        SenseDeviceReading("always_on", "Always On", "always_on", 125.0, True, 0.0),
        SenseDeviceReading("mystery-id", "Other", "unknown", 75.0, True, 0.0),
    )

    assert _bucket_power(devices, {"always_on", "always on"}) == 125.0
    assert _bucket_power(devices, {"unknown", "other"}) == 75.0
    assert _bucket_power(devices, {"solar"}) is None
