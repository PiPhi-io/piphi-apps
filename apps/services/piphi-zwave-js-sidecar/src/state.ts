import {
  AutomationRegistry,
  FileAutomationIdempotencyStore,
  buildLocalEventRecord,
  createRuntimeStarter,
  type RuntimeRegistry,
} from "piphi-runtime-kit-node";

import { commands } from "./contract.js";
import { integrationId, integrationName, integrationVersion } from "./settings.js";
import type { DeviceConfig, DeviceEntry, DeviceState } from "./types.js";

export const starter = createRuntimeStarter({
  integrationId,
  integrationName,
  version: integrationVersion,
});

export const runtime = starter.runtime;
export const registry = starter.registry as unknown as RuntimeRegistry<
  DeviceState,
  DeviceEntry,
  Record<string, unknown>
>;
export const telemetry = starter.telemetryClient;
export const configSync = starter.configSync;
export const automations = new AutomationRegistry({
  idempotencyStore: new FileAutomationIdempotencyStore(
    process.env.PIPHI_AUTOMATION_LEDGER_DIR ?? "./data/automation-actions",
  ),
});

export function buildEntry(config: DeviceConfig): DeviceEntry {
  return {
    configId: config.configId ?? config.id,
    deviceId: config.deviceId ?? config.id,
    containerId: config.containerId,
    integrationId: config.integrationId ?? integrationId,
    host: config.host,
    alias: config.alias,
    config,
  };
}

export async function applyConfig(config: DeviceConfig): Promise<void> {
  const entry = buildEntry(config);
  registry.set(config.id, entry);
  registry.updateState(
    config.id,
    {
      connected: true,
      host: config.host,
      alias: config.alias,
    },
  );
  appendRuntimeEvent("runtime.config.applied", entry, {
    host: config.host,
    alias: config.alias ?? null,
  });
}

export async function removeConfig(configId: string): Promise<boolean> {
  const entry = registry.remove(configId);
  if (!entry) {
    return false;
  }
  appendRuntimeEvent("runtime.config.removed", entry, {
    host: entry.host,
    alias: entry.alias ?? null,
  });
  return true;
}

export function appendRuntimeEvent(
  eventType: string,
  entry: Partial<DeviceEntry> & { deviceId: string; configId: string },
  payload: Record<string, unknown>,
) {
  return registry.appendEvent(
    buildLocalEventRecord({
      eventType,
      deviceId: entry.deviceId,
      configId: entry.configId,
      containerId: entry.containerId ?? runtime.auth.containerId ?? null,
      integrationId: entry.integrationId ?? integrationId,
      source: integrationId,
      severity: "info",
      payload,
    }),
  );
}

for (const commandName of Object.keys(commands)) {
  automations.action(commandName, {
    label: commands[commandName as keyof typeof commands].description,
  })((request) => {
    const target = request.target && typeof request.target === "object"
      ? request.target as Record<string, unknown>
      : {};
    const deviceId = String(request.deviceId ?? target.device_id ?? "zwave-js-service");
    const configId = String(request.configId ?? target.config_id ?? deviceId);
    const entry = registry.get(configId) ?? { deviceId, configId };
    const event = appendRuntimeEvent("runtime.command.received", entry, {
      command: commandName,
      device_id: deviceId,
      entity_id: request.entityId ?? null,
      args: request.args,
      target,
    });
    return {
      event,
      command: commandName,
      device_id: deviceId,
      config_id: configId,
      target,
      params: request.args,
    };
  });
}
