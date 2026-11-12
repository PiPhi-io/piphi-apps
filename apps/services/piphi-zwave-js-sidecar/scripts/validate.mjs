import fs from "node:fs";

const manifest = JSON.parse(fs.readFileSync("manifest.json", "utf8"));
const behaviorPath = fs.existsSync("src/behaviors.json") ? "src/behaviors.json" : "behaviors.json";
const behavior = fs.existsSync(behaviorPath) ? JSON.parse(fs.readFileSync(behaviorPath, "utf8")) : null;
const dockerfile = fs.existsSync("Dockerfile") ? fs.readFileSync("Dockerfile", "utf8") : "";
const required = ["health", "entities", "command", "config", "ui_config"];
const endpoints = manifest.api?.endpoints ?? {};
const errors = [];
const riskLevels = new Set(["low", "medium", "high", "critical"]);
const automationSchemaVersions = new Set(["automation.behavior.v1", "automation.behavior.v2"]);

if (manifest.$schema !== "./schema/piphi-manifest.schema.json") {
  errors.push("manifest must reference ./schema/piphi-manifest.schema.json");
}
if (!fs.existsSync("schema/piphi-manifest.schema.json")) {
  errors.push("schema/piphi-manifest.schema.json is missing");
}

for (const key of required) {
  if (!manifest.api?.required?.includes(key)) {
    errors.push(`api.required is missing ${key}`);
  }
  if (typeof endpoints[key] !== "string" || !endpoints[key].startsWith("/")) {
    errors.push(`api.endpoints.${key} must be an absolute path`);
  }
}

const port = manifest.runtime?.linux?.container?.ports?.[0]?.container;
if (!Number.isInteger(port)) {
  errors.push("runtime.linux.container.ports[0].container must be an integer");
} else if (dockerfile && !dockerfile.includes(`EXPOSE ${port}`)) {
  errors.push(`Dockerfile must expose manifest port ${port}`);
}

for (const [capabilityId, capability] of Object.entries(manifest.capabilities ?? {})) {
  if (capability?.kind === "action" && !manifest.commands?.[capabilityId]) {
    errors.push(`action capability ${capabilityId} must map to a command`);
  }
}

const isSidecar = manifest.metadata?.domain === "sidecar-service";

if (!behavior && !isSidecar) {
  errors.push("behaviors.json is missing");
} else if (behavior) {
  if (behavior.behaviorSchemaVersion !== "integration.behaviors.v2") {
    errors.push("behaviors.json must use behaviorSchemaVersion integration.behaviors.v2");
  }
  const deviceIds = new Set();
  for (const [deviceIndex, device] of (behavior.devices ?? []).entries()) {
    if (deviceIds.has(device.id)) {
      errors.push(`behaviors.devices[${deviceIndex}].id duplicates another device id`);
    }
    deviceIds.add(device.id);
    const actionIds = new Set();
    for (const [actionIndex, action] of (device.actions ?? []).entries()) {
      if (actionIds.has(action.id)) {
        errors.push(`behaviors.devices[${deviceIndex}].actions[${actionIndex}].id duplicates another action id`);
      }
      actionIds.add(action.id);
      if (typeof action.runtime?.command !== "string" || action.runtime.command.trim() === "") {
        errors.push(`behaviors.devices[${deviceIndex}].actions[${actionIndex}].runtime.command is required`);
      }
      const riskLevel = action.safety?.riskLevel ?? action.riskLevel ?? action.runtime?.riskLevel;
      if (typeof riskLevel !== "string" || !riskLevels.has(riskLevel)) {
        errors.push(`behaviors.devices[${deviceIndex}].actions[${actionIndex}].safety.riskLevel must be low, medium, high, or critical`);
      }
    }
  }
  if ((behavior.devices ?? []).length === 0 && (behavior.templates ?? []).length === 0) {
    errors.push("behaviors.json must define at least one device or template");
  }
  for (const [templateIndex, template] of (behavior.templates ?? []).entries()) {
    if (template.deviceKey && !deviceIds.has(template.deviceKey)) {
      errors.push(`behaviors.templates[${templateIndex}].deviceKey must reference a defined device`);
    }
    const automationSchemaVersion = template.config?.automation_schema_version;
    if (automationSchemaVersion && !automationSchemaVersions.has(automationSchemaVersion)) {
      errors.push(`behaviors.templates[${templateIndex}].config.automation_schema_version is unsupported`);
    }
  }
}

if (errors.length > 0) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log("PiPhi scaffold validation passed.");
