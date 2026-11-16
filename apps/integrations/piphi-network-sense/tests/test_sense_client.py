from piphi_network_sense.sense_client import (
    SenseAuthenticationError,
    SenseDeviceReading,
    SenseRateLimitError,
    SenseTransientError,
    _bucket_power,
    _translate_read_error,
)


def test_realtime_bucket_power_falls_back_by_id_or_name() -> None:
    devices = (
        SenseDeviceReading("always_on", "Always On", "always_on", 125.0, True, 0.0),
        SenseDeviceReading("mystery-id", "Other", "unknown", 75.0, True, 0.0),
    )

    assert _bucket_power(devices, {"always_on", "always on"}) == 125.0
    assert _bucket_power(devices, {"unknown", "other"}) == 75.0
    assert _bucket_power(devices, {"solar"}) is None


def test_unofficial_api_errors_are_classified_without_leaking_canary_data() -> None:
    auth = type("AuthFailure", (Exception,), {"status": 401})("canary-secret")
    quota = type("ProviderFailure", (Exception,), {"status": 429})("canary-secret")
    outage = RuntimeError("https://api.sense.com/private?token=canary-secret")

    translated = [
        _translate_read_error(auth),
        _translate_read_error(quota),
        _translate_read_error(outage),
    ]

    assert isinstance(translated[0], SenseAuthenticationError)
    assert isinstance(translated[1], SenseRateLimitError)
    assert isinstance(translated[2], SenseTransientError)
    assert "canary-secret" not in " ".join(map(str, translated))
