from __future__ import annotations

from typing import Literal

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class WakeOnLanTarget(BaseModel):
    """A named, immutable Wake-on-LAN destination exposed to automations."""

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    label: str
    interface: str
    mac_addr: str

    @field_validator("label", "interface", "mac_addr")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("mac_addr")
    @classmethod
    def validate_mac(cls, value: str) -> str:
        normalized = value.replace("-", ":").lower()
        parts = normalized.split(":")
        if len(parts) != 6 or any(
            len(part) != 2 or any(char not in "0123456789abcdef" for char in part)
            for part in parts
        ):
            raise ValueError("mac_addr must be a six-byte MAC address")
        return normalized


class DeviceConfig(RuntimeConfig):
    """Connection settings for one pfSense firewall."""

    host: str = ""
    api_key: SecretStr = SecretStr("")
    alias: str | None = "pfSense Firewall"
    port: int = Field(default=443, ge=1, le=65535)
    scheme: Literal["https", "http"] = "https"
    verify_tls: bool = True
    ca_bundle_path: str | None = None
    poll_interval_seconds: int = Field(default=60, ge=30, le=3600)
    collect_dhcp_leases: bool = False
    collect_vpn_status: bool = False
    collect_client_inventory: bool = False
    collect_security_logs: bool = False
    collect_certificates: bool = False
    collect_ha_status: bool = False
    enable_diagnostic_ping: bool = False
    allowed_ping_hosts: list[str] = Field(default_factory=list)
    enable_service_restart: bool = False
    enable_service_start: bool = False
    allowed_services: list[str] = Field(default_factory=list)
    enable_wake_on_lan: bool = False
    wake_on_lan_targets: list[WakeOnLanTarget] = Field(default_factory=list)
    simulation_mode: bool = False

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if "/" in normalized or "://" in normalized:
            raise ValueError("host must be a hostname or IP address, not a URL")
        return normalized

    @field_validator("ca_bundle_path")
    @classmethod
    def normalize_ca_bundle(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @field_validator("allowed_ping_hosts", "allowed_services")
    @classmethod
    def normalize_allowlist(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            key = item.casefold()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized

    @model_validator(mode="after")
    def validate_transport_security(self) -> DeviceConfig:
        if not self.simulation_mode and not self.host:
            raise ValueError("host is required unless simulation mode is enabled")
        if not self.simulation_mode and not self.secret_api_key().strip():
            raise ValueError("api_key is required unless simulation mode is enabled")
        if self.scheme == "http" and self.verify_tls:
            raise ValueError("verify_tls must be false when scheme is http")
        if self.ca_bundle_path and not self.verify_tls:
            raise ValueError("ca_bundle_path requires verify_tls=true")
        if self.enable_diagnostic_ping and not self.allowed_ping_hosts:
            raise ValueError(
                "allowed_ping_hosts must not be empty when diagnostic ping is enabled"
            )
        if (
            self.enable_service_restart or self.enable_service_start
        ) and not self.allowed_services:
            raise ValueError(
                "allowed_services must not be empty when service control is enabled"
            )
        if self.enable_wake_on_lan and not self.wake_on_lan_targets:
            raise ValueError(
                "wake_on_lan_targets must not be empty when Wake-on-LAN is enabled"
            )
        target_ids = [target.id.casefold() for target in self.wake_on_lan_targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("wake_on_lan_targets IDs must be unique")
        return self

    @property
    def base_url(self) -> str:
        if self.simulation_mode:
            return "simulator://pfsense"
        default_port = 443 if self.scheme == "https" else 80
        suffix = "" if self.port == default_port else f":{self.port}"
        return f"{self.scheme}://{self.host}{suffix}"

    def secret_api_key(self) -> str:
        return self.api_key.get_secret_value()
