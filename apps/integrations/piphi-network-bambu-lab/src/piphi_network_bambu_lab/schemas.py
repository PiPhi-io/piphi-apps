from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from pydantic import SecretStr, field_validator, model_validator
from piphi_runtime_kit_python import RuntimeConfig

PRIVATE_LAN_RANGES = (
    IPv4Network("10.0.0.0/8"),
    IPv4Network("172.16.0.0/12"),
    IPv4Network("192.168.0.0/16"),
)


class DeviceConfig(RuntimeConfig):
    host: str | None = None
    alias: str | None = None
    serial: str | None = None
    access_code: SecretStr | None = None
    developer_mode_acknowledged: bool = False
    simulation_mode: bool = False

    @field_validator("host")
    @classmethod
    def validate_lan_ip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            address = IPv4Address(value.strip())
        except ValueError as exc:
            raise ValueError("host must be a private LAN IPv4 address") from exc
        if not any(address in network for network in PRIVATE_LAN_RANGES):
            raise ValueError("host must be a private LAN IPv4 address")
        return str(address)

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, value: str | None) -> str | None:
        if value is None:
            return None
        serial = value.strip().upper()
        if not 8 <= len(serial) <= 32 or not serial.isascii() or not serial.isalnum():
            raise ValueError("invalid printer serial")
        return serial

    @model_validator(mode="after")
    def validate_real_or_simulated(self) -> DeviceConfig:
        if self.simulation_mode:
            if any((self.host, self.serial, self.access_code)):
                raise ValueError("simulated printer must not include real host or credentials")
            return self
        if not self.host or not self.serial or self.access_code is None:
            raise ValueError("real printer requires host, serial, and LAN access code")
        if not 8 <= len(self.access_code.get_secret_value()) <= 64:
            raise ValueError("LAN access code must be 8-64 characters")
        if not self.developer_mode_acknowledged:
            raise ValueError("Developer Mode acknowledgement is required")
        return self
