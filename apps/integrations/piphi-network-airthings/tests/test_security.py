from __future__ import annotations

from pydantic import SecretStr

from piphi_network_airthings.security import REDACTED, redact_sensitive


def test_recursive_redaction_covers_nested_keys_secret_types_and_canary_values() -> None:
    canary = "nested-canary-never-visible"
    payload = {
        "safe": [
            {"authorization": f"Bearer {canary}"},
            {"nested": (SecretStr("typed-secret"), f"prefix-{canary}-suffix")},
        ],
        "device": {"serialNumber": "private-serial", "temperature_c": 21.0},
    }

    sanitized = redact_sensitive(payload, secrets=(canary,))

    assert sanitized["safe"][0]["authorization"] == REDACTED
    assert sanitized["safe"][1]["nested"] == [REDACTED, f"prefix-{REDACTED}-suffix"]
    assert sanitized["device"]["serialNumber"] == REDACTED
    assert sanitized["device"]["temperature_c"] == 21.0
    assert canary not in str(sanitized)
