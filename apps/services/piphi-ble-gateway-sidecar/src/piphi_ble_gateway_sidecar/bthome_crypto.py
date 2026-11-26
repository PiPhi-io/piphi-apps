from __future__ import annotations

import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

BTHOME_UUIDS = {
    "fcd2",
    "0000fcd2",
    "0000fcd2-0000-1000-8000-00805f9b34fb",
}


class BTHomeDecryptionError(ValueError):
    """The encrypted advertisement did not authenticate with the scoped key."""


def address_bytes(address: str) -> bytes:
    compact = re.sub(r"[^0-9A-Fa-f]", "", address)
    if len(compact) != 12:
        raise BTHomeDecryptionError("invalid BLE identity for BTHome nonce")
    return bytes.fromhex(compact)


def decrypt_bthome(address: str, payload: bytes, bind_key: bytes) -> bytes:
    """Authenticate and decrypt one BTHome v2 service-data payload.

    BTHome's nonce is the advertiser identity, little-endian service UUID,
    device-info byte, and four-byte counter. The raw identity and key remain
    inside the gateway and are never included in the returned envelope.
    """
    if len(bind_key) != 16 or len(payload) < 9 or payload[0] & 0x01 == 0:
        raise BTHomeDecryptionError("invalid encrypted BTHome payload")
    device_info = payload[:1]
    counter = payload[-8:-4]
    ciphertext_and_tag = payload[1:-8] + payload[-4:]
    nonce = address_bytes(address) + bytes.fromhex("d2fc") + device_info + counter
    try:
        plaintext = AESCCM(bind_key, tag_length=4).decrypt(nonce, ciphertext_and_tag, None)
    except InvalidTag as exc:
        raise BTHomeDecryptionError("BTHome authentication failed") from exc
    return bytes([payload[0] & 0xFE]) + plaintext


def encrypt_bthome_fixture(address: str, plaintext_payload: bytes, bind_key: bytes, counter: bytes) -> bytes:
    """Deterministic helper for protocol fixtures; not used by production scanning."""
    if len(counter) != 4 or not plaintext_payload:
        raise ValueError("fixture counter and payload are invalid")
    device_info = bytes([plaintext_payload[0] | 0x01])
    nonce = address_bytes(address) + bytes.fromhex("d2fc") + device_info + counter
    encrypted = AESCCM(bind_key, tag_length=4).encrypt(nonce, plaintext_payload[1:], None)
    return device_info + encrypted[:-4] + counter + encrypted[-4:]
