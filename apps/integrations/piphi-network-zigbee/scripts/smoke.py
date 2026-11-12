from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8730").rstrip("/")
DEFAULT_SIDECAR_URL = os.getenv("ZIGBEE2MQTT_SIDECAR_URL", "http://127.0.0.1:8720").rstrip("/")
DEFAULT_MQTT_SERVER = os.getenv("MQTT_SERVER", "mqtt://127.0.0.1:1883")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PiPhi Zigbee integration smoke checks against a running server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--sidecar-url", default=DEFAULT_SIDECAR_URL)
    parser.add_argument("--mqtt-server", default=DEFAULT_MQTT_SERVER)
    parser.add_argument("--skip-sidecar", action="store_true")
    parser.add_argument("--live-mqtt", action="store_true", help="Publish real MQTT commands instead of dry-run command checks.")
    args = parser.parse_args()

    checks = SmokeChecks(
        base_url=args.base_url.rstrip("/"),
        sidecar_url=args.sidecar_url.rstrip("/"),
        mqtt_server=args.mqtt_server,
        skip_sidecar=args.skip_sidecar,
        dry_run_commands=not args.live_mqtt,
    )
    checks.run()
    print("PiPhi Zigbee smoke checks passed.")
    return 0


class SmokeChecks:
    def __init__(
        self,
        *,
        base_url: str,
        sidecar_url: str,
        mqtt_server: str,
        skip_sidecar: bool,
        dry_run_commands: bool,
    ) -> None:
        self.base_url = base_url
        self.sidecar_url = sidecar_url
        self.mqtt_server = mqtt_server
        self.skip_sidecar = skip_sidecar
        self.dry_run_commands = dry_run_commands

    def run(self) -> None:
        self._check_integration_contract()
        self._check_discovery_config_command_state()
        if not self.skip_sidecar:
            self._check_sidecar_contract()

    def _check_integration_contract(self) -> None:
        health = self.get_json(f"{self.base_url}/health")
        self.require_any(health, ("ok", "status"), "integration health response")
        ui_config = self.get_json(f"{self.base_url}/ui-config")
        self.require_keys(ui_config, ("schema", "uiSchema"), "integration ui-config")
        contract = self.get_json(f"{self.base_url}/contract")
        self.require_keys(contract, ("integration_id", "endpoints", "required"), "integration contract")

    def _check_discovery_config_command_state(self) -> None:
        discovered = self.post_json(
            f"{self.base_url}/discover",
            {
                "inputs": {
                    "device": {
                        "friendly_name": "smoke_light",
                        "ieee_address": "0x00158d0000smoke01",
                        "definition": {
                            "model": "SMOKE-TEST",
                            "vendor": "PiPhi",
                            "exposes": [
                                {
                                    "type": "light",
                                    "features": [
                                        {"property": "state", "access": 7},
                                        {"property": "brightness", "access": 7},
                                    ],
                                }
                            ],
                        },
                    }
                }
            },
        )
        devices = discovered.get("devices")
        if not isinstance(devices, list) or not devices:
            raise SmokeFailure("discovery did not return devices")

        config_id = "smoke-light"
        config = self.post_json(
            f"{self.base_url}/config",
            {
                "id": config_id,
                "friendly_name": "smoke_light",
                "alias": "Smoke Light",
                "ieee_address": "0x00158d0000smoke01",
                "mqtt_server": self.mqtt_server,
                "mqtt_base_topic": "zigbee2mqtt",
                "capabilities": ["state", "brightness_percent"],
                "exposes": devices[0].get("exposes", []),
                "capability_metadata": devices[0].get("capability_metadata", {}),
            },
        )
        self.require_any(config, ("ok", "status"), "config response")

        command = self.post_json(
            f"{self.base_url}/command",
            {
                "contract_version": "automation.runtime.command.v1",
                "command": "set_state",
                "target": {"config_id": config_id, "device_id": config_id},
                "params": {"on": True},
                "capability": "action.set_state",
                "capability_requirements": ["action.set_state"],
                "dry_run": self.dry_run_commands,
            },
        )
        if command.get("ok") is not True:
            raise SmokeFailure(f"command response not ok: {command}")
        mqtt = command.get("mqtt") if isinstance(command.get("mqtt"), dict) else {}
        if mqtt.get("topic") != "zigbee2mqtt/smoke_light/set":
            raise SmokeFailure(f"unexpected command MQTT topic: {mqtt}")

        state = self.get_json(f"{self.base_url}/state")
        self.require_keys(state, ("summary", "entries", "state_snapshots", "mqtt_subscriptions"), "state response")

    def _check_sidecar_contract(self) -> None:
        try:
            health = self.get_json(f"{self.sidecar_url}/health")
        except SmokeFailure as exc:
            raise SmokeFailure(f"sidecar check failed; pass --skip-sidecar to skip: {exc}") from exc
        self.require_any(health, ("ok", "status"), "sidecar health response")
        snapshot = self.get_json(f"{self.sidecar_url}/v1/snapshot")
        self.require_keys(snapshot, ("configured", "service"), "sidecar snapshot")
        devices = self.post_json(
            f"{self.sidecar_url}/v1/devices",
            {"server": self.mqtt_server, "base_topic": "zigbee2mqtt", "dry_run": True},
        )
        self.require_keys(devices, ("ok", "status", "response_topic"), "sidecar devices dry-run")

    def get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"accept": "application/json"})
        return self._request_json(request)

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=encoded,
            headers={"accept": "application/json", "content-type": "application/json"},
            method="POST",
        )
        return self._request_json(request)

    def _request_json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"{request.full_url} failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise SmokeFailure(f"{request.full_url} returned a non-object payload")
        return payload

    @staticmethod
    def require_keys(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
        missing = [key for key in keys if key not in payload]
        if missing:
            raise SmokeFailure(f"{label} missing keys: {', '.join(missing)}")

    @staticmethod
    def require_any(payload: dict[str, Any], keys: tuple[str, ...], label: str) -> None:
        if not any(key in payload for key in keys):
            raise SmokeFailure(f"{label} missing one of: {', '.join(keys)}")


class SmokeFailure(RuntimeError):
    pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"smoke.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
