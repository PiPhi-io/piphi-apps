from __future__ import annotations

import json
from pathlib import Path

from piphi_network_sense.contract import CAPABILITIES, COMMANDS, ENDPOINTS, REQUIRED_ENDPOINTS

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "manifest.json").read_text())
behavior_path = ROOT / "src" / "behaviors.json"
if not behavior_path.exists():
    behavior_path = ROOT / "behaviors.json"
behavior = json.loads(behavior_path.read_text()) if behavior_path.exists() else None
dockerfile = (ROOT / "Dockerfile").read_text() if (ROOT / "Dockerfile").exists() else ""
errors: list[str] = []
risk_levels = {"low", "medium", "high", "critical"}
automation_schema_versions = {"automation.behavior.v1", "automation.behavior.v2"}

if manifest.get("$schema") != "./schema/piphi-manifest.schema.json":
    errors.append("manifest must reference ./schema/piphi-manifest.schema.json")
if not (ROOT / "schema" / "piphi-manifest.schema.json").exists():
    errors.append("schema/piphi-manifest.schema.json is missing")

maximum_instances = manifest.get("config", {}).get("maximum_instances")
if maximum_instances != 1:
    errors.append("Sense manifest config.maximum_instances must equal 1")

for key in REQUIRED_ENDPOINTS:
    if key not in manifest.get("api", {}).get("required", []):
        errors.append(f"api.required is missing {key}")
    endpoint = manifest.get("api", {}).get("endpoints", {}).get(key)
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        errors.append(f"api.endpoints.{key} must be an absolute path")
    if ENDPOINTS.get(key) != endpoint:
        errors.append(f"contract endpoint {key} does not match manifest")

port = manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("ports", [{}])[0].get("container")
if not isinstance(port, int):
    errors.append("runtime.linux.container.ports[0].container must be an integer")
elif dockerfile and f"EXPOSE {port}" not in dockerfile:
    errors.append(f"Dockerfile must expose manifest port {port}")

for capability_id, capability in manifest.get("capabilities", {}).items():
    if capability.get("kind") == "action" and capability_id not in COMMANDS:
        errors.append(f"action capability {capability_id} must map to a command")

if behavior is None:
    errors.append("behaviors.json is missing")
else:
    if behavior.get("behaviorSchemaVersion") != "integration.behaviors.v2":
        errors.append("behaviors.json must use behaviorSchemaVersion integration.behaviors.v2")
    telemetry_mappings = behavior.get("telemetry", {}).get("capabilityMappings", [])
    mapped_capabilities: set[str] = set()
    for mapping_index, mapping in enumerate(telemetry_mappings):
        native_metric = str(mapping.get("nativeMetric") or "")
        canonical_capability = str(mapping.get("capability") or "")
        is_known_metric = native_metric in CAPABILITIES or (
            native_metric == "is_on" and canonical_capability == "sensor.device_on"
        )
        if not is_known_metric:
            errors.append(
                f"behaviors.telemetry.capabilityMappings[{mapping_index}] references unknown metric"
            )
        if "." not in canonical_capability or canonical_capability.startswith("telemetry."):
            errors.append(
                f"behaviors.telemetry.capabilityMappings[{mapping_index}] must use a canonical dotted capability"
            )
        if canonical_capability in mapped_capabilities:
            errors.append(
                f"behaviors.telemetry.capabilityMappings[{mapping_index}] duplicates a capability"
            )
        mapped_capabilities.add(canonical_capability)

    device_ids: set[str] = set()
    for device_index, device in enumerate(behavior.get("devices") or []):
        device_id = str(device.get("id") or "").strip()
        if device_id in device_ids:
            errors.append(f"behaviors.devices[{device_index}].id duplicates another device id")
        if device_id:
            device_ids.add(device_id)
        for capability in device.get("capabilities") or []:
            if capability not in CAPABILITIES:
                errors.append(
                    f"behaviors.devices[{device_index}] references unknown capability {capability}"
                )
        for group_name in ("triggers", "conditions"):
            for option_index, option in enumerate(device.get(group_name) or []):
                capability = str(option.get("capability") or "")
                if capability not in mapped_capabilities and capability != "telemetry.state":
                    errors.append(
                        f"behaviors.devices[{device_index}].{group_name}[{option_index}] capability is not mapped"
                    )
        action_ids: set[str] = set()
        for action_index, action in enumerate(device.get("actions") or []):
            action_id = str(action.get("id") or "").strip()
            if action_id in action_ids:
                errors.append(f"behaviors.devices[{device_index}].actions[{action_index}].id duplicates another action id")
            if action_id:
                action_ids.add(action_id)
            runtime = action.get("runtime") if isinstance(action.get("runtime"), dict) else {}
            safety = action.get("safety") if isinstance(action.get("safety"), dict) else {}
            command = str(runtime.get("command") or "").strip()
            risk_level = str(safety.get("riskLevel") or action.get("riskLevel") or runtime.get("riskLevel") or "").strip()
            if not command:
                errors.append(f"behaviors.devices[{device_index}].actions[{action_index}].runtime.command is required")
            if risk_level not in risk_levels:
                errors.append(f"behaviors.devices[{device_index}].actions[{action_index}].safety.riskLevel must be low, medium, high, or critical")
    if not behavior.get("devices") and not behavior.get("templates"):
        errors.append("behaviors.json must define at least one device or template")
    for template_index, template in enumerate(behavior.get("templates") or []):
        device_key = str(template.get("deviceKey") or template.get("device_key") or "").strip()
        if device_key and device_ids and device_key not in device_ids:
            errors.append(f"behaviors.templates[{template_index}].deviceKey must reference a defined device")
        config = template.get("config") if isinstance(template.get("config"), dict) else {}
        automation_schema_version = str(config.get("automation_schema_version") or "").strip()
        if automation_schema_version and automation_schema_version not in automation_schema_versions:
            errors.append(f"behaviors.templates[{template_index}].config.automation_schema_version is unsupported")

if errors:
    raise SystemExit("\n".join(errors))

print("PiPhi scaffold validation passed.")
