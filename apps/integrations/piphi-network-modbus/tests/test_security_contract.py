from __future__ import annotations

import hashlib
import hmac

import pytest

from piphi_network_modbus.profile_codec import profile_hash
from piphi_network_modbus.schemas import DeviceConfig
from piphi_network_modbus.security import redact, verify_profile_trust


def test_recursive_redaction_covers_nested_credentials_and_serial_identity() -> None:
    payload = {
        "transport": {"password": "private", "nested": [{"serial_port": "/dev/private"}]},
        "authorization": "Bearer private",
        "safe": "retained",
    }
    assert redact(payload) == {
        "transport": {"password": "[redacted]", "nested": [{"serial_port": "[redacted]"}]},
        "authorization": "[redacted]",
        "safe": "retained",
    }


def test_profile_trust_requires_matching_digest_and_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    config = DeviceConfig.model_validate(
        {
            "id": "trusted",
            "host": "127.0.0.1",
            "points": [{"id": "value", "name": "Value", "unit_id": 1, "address": 0}],
        }
    )
    digest = profile_hash(
        profile_id=config.profile_id,
        profile_version=config.profile_version,
        profile_provenance=config.profile_provenance,
        points=config.points,
        semantic_bindings={"composites": [], "coil_commands": []},
    )
    anchor = "test-profile-trust-anchor"
    signature = hmac.new(anchor.encode(), digest.encode(), hashlib.sha256).hexdigest()
    monkeypatch.setenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", anchor)
    verify_profile_trust(digest=digest, declared_digest=digest, signature=signature)
    with pytest.raises(ValueError, match="profile_signature_invalid"):
        verify_profile_trust(digest=digest, declared_digest=digest, signature="0" * 64)


def test_production_profile_fails_closed_without_trust_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", raising=False)
    with pytest.raises(ValueError, match="trusted_profile_proof_required"):
        verify_profile_trust(digest="a" * 64, declared_digest=None, signature=None)
