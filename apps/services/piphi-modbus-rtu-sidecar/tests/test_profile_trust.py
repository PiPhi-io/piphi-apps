from __future__ import annotations

import hashlib
import hmac

import pytest

from piphi_modbus_rtu_sidecar.profile import profile_hash
from piphi_modbus_rtu_sidecar.schemas import DeviceConfig
from piphi_modbus_rtu_sidecar.security import redact, verify_profile_trust


def test_sidecar_verifies_transport_profile_and_recursively_redacts(monkeypatch: pytest.MonkeyPatch) -> None:
    config = DeviceConfig.model_validate(
        {
            "id": "trusted-bus",
            "serial_port": "/dev/serial/by-id/private-adapter",
            "registers": [{"id": "value", "name": "Value", "unit_id": 1, "address": 0}],
        }
    )
    digest = profile_hash(config)
    anchor = "test-profile-trust-anchor"
    signature = hmac.new(anchor.encode(), digest.encode(), hashlib.sha256).hexdigest()
    monkeypatch.setenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", anchor)
    verify_profile_trust(digest=digest, declared_digest=digest, signature=signature)
    assert redact({"nested": [{"serial_port": config.serial_port}], "token": "secret"}) == {
        "nested": [{"serial_port": "[redacted]"}],
        "token": "[redacted]",
    }


def test_sidecar_rejects_unsigned_production_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", raising=False)
    with pytest.raises(ValueError, match="trusted_profile_proof_required"):
        verify_profile_trust(digest="a" * 64, declared_digest=None, signature=None)
