import crypto from "node:crypto";

import {
  RuntimeContext,
  RuntimeRegistry,
} from "piphi-runtime-kit-node";

const MAX_RUNTIME_EVENTS = 100;

export interface FixDetails {
  signal_state: string;
  fix_quality: string;
  position_source: string;
  stale: boolean;
  last_sentence_at: string | null;
  last_fix_at: string | null;
  last_valid_fix_at: string | null;
  fix_age_ms: number | null;
  satellites: number | null;
  hdop: number | null;
  altitude_meters: number | null;
}

export interface DeviceRuntimeState extends Record<string, unknown> {
  deviceId: string;
  path: string | null;
  connected: boolean;
  fix_status: string;
  lastMetrics: Record<string, unknown>;
  fix_details: FixDetails;
  discovery: object | null;
  updatedAt: string | null;
  containerId?: string | null;
  configName?: string | null;
  configuredAt?: string;
  latestState?: DeviceRuntimeState;
  lastUpdated?: string;
}

export interface ActiveConfig {
  configId: string;
  deviceId: string;
  integrationId: string | null;
  path: string | null;
  containerId: string | null;
  configName: string;
  configuredAt: string;
}

export interface RuntimeEvent extends Record<string, unknown> {
  event_id: string;
  type: string;
  ts: string;
  severity: string;
  device_id: string | null;
  data: Record<string, unknown>;
  receivedAt?: string;
}

interface RuntimeErrorSnapshot {
  message: string;
  ts: string;
}

interface TelemetryRuntimeSnapshot {
  publishedCount: number;
  lastPayload: Record<string, unknown> | null;
  lastPublishedAt: string | null;
  lastDelivery: string;
}

interface MqttRuntimeSnapshot {
  connected: boolean;
}

function createDefaultFixDetails(): FixDetails {
  return {
    signal_state: "idle",
    fix_quality: "unknown",
    position_source: "none",
    stale: false,
    last_sentence_at: null,
    last_fix_at: null,
    last_valid_fix_at: null,
    fix_age_ms: null,
    satellites: null,
    hdop: null,
    altitude_meters: null,
  };
}

function createDefaultDeviceState(deviceId: string, path: string | null = null): DeviceRuntimeState {
  return {
    deviceId,
    path,
    connected: false,
    fix_status: "idle",
    lastMetrics: {},
    fix_details: createDefaultFixDetails(),
    discovery: null,
    updatedAt: null,
  };
}

const runtimeContext = new RuntimeContext();
runtimeContext.auth.update({
  containerId: process.env.PIPHI_CONTAINER_ID ?? null,
  internalToken: process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? null,
});
if (process.env.PIPHI_CORE_BASE_URL) {
  runtimeContext.processState.coreBaseUrl = process.env.PIPHI_CORE_BASE_URL;
}

const registry = new RuntimeRegistry<DeviceRuntimeState, DeviceRuntimeState, RuntimeEvent>(
  MAX_RUNTIME_EVENTS,
);

const activeConfigs: Record<string, ActiveConfig> = {};

const runtimeMetadata: {
  startedAt: string;
  status: string;
  telemetry: TelemetryRuntimeSnapshot;
  mqtt: MqttRuntimeSnapshot;
  lastError: RuntimeErrorSnapshot | null;
} = {
  startedAt: new Date().toISOString(),
  status: "starting",
  telemetry: {
    publishedCount: 0,
    lastPayload: null,
    lastPublishedAt: null,
    lastDelivery: "idle",
  },
  mqtt: {
    connected: false,
  },
  lastError: null,
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function getDeviceMap(): Record<string, DeviceRuntimeState> {
  const devices: Record<string, DeviceRuntimeState> = {};
  for (const deviceId of registry.ids()) {
    const device = registry.get(deviceId);
    if (device) {
      devices[deviceId] = clone(device);
    }
  }
  return devices;
}

export function getRuntimeContext(): RuntimeContext {
  return runtimeContext;
}

export function getRuntimeRegistry(): RuntimeRegistry<DeviceRuntimeState, DeviceRuntimeState, RuntimeEvent> {
  return registry;
}

export function setRuntimeStatus(status: string): void {
  runtimeMetadata.status = status;
}

export function setMqttStatus(connected: boolean): void {
  runtimeMetadata.mqtt.connected = Boolean(connected);
}

export function setRuntimeError(error: unknown): void {
  runtimeMetadata.lastError = {
    message: error instanceof Error ? error.message : String(error),
    ts: new Date().toISOString(),
  };
}

export function clearRuntimeError(): void {
  runtimeMetadata.lastError = null;
}

export function upsertActiveConfig(config: {
  configId?: string;
  deviceId?: string;
  id?: string;
  path?: string | null;
  containerId?: string | null;
  integrationId?: string | null;
  configName?: string;
}): ActiveConfig {
  const deviceId = config.deviceId || config.id || config.path;
  if (!deviceId) {
    throw new Error("A device id, id, or path is required to upsert an active config");
  }

  const activeConfig: ActiveConfig = {
    configId: config.configId ?? deviceId,
    deviceId,
    integrationId: config.integrationId ?? null,
    path: config.path ?? null,
    containerId: config.containerId ?? null,
    configName: config.configName ?? config.path ?? deviceId,
    configuredAt: new Date().toISOString(),
  };
  activeConfigs[deviceId] = activeConfig;

  const existingDevice = registry.get(deviceId) ?? createDefaultDeviceState(deviceId, config.path ?? null);
  registry.set(deviceId, {
    ...existingDevice,
    path: config.path ?? existingDevice.path,
    containerId: activeConfig.containerId,
    configName: activeConfig.configName,
    configuredAt: activeConfig.configuredAt,
  });
  runtimeMetadata.status = "configured";
  return activeConfig;
}

export function removeActiveConfig(deviceId: string): void {
  delete activeConfigs[deviceId];
  if (Object.keys(activeConfigs).length === 0) {
    runtimeMetadata.status = "idle";
  }
}

export function updateDeviceRuntime(
  deviceId: string,
  patch: Omit<Partial<DeviceRuntimeState>, "fix_details"> & { fix_details?: Partial<FixDetails> },
): DeviceRuntimeState {
  const patchPath =
    typeof patch.path === "string" || patch.path === null ? patch.path : null;
  const existingDevice = registry.get(deviceId) ?? createDefaultDeviceState(deviceId, patchPath);
  const updatedDevice: DeviceRuntimeState = {
    ...existingDevice,
    ...patch,
    fix_details: {
      ...existingDevice.fix_details,
      ...(patch.fix_details ?? {}),
    },
    updatedAt: new Date().toISOString(),
  };
  registry.set(deviceId, updatedDevice);
  return updatedDevice;
}

export function recordRuntimeEvent({
  type,
  severity = "info",
  device_id = null,
  data = {},
}: {
  type: string;
  severity?: string;
  device_id?: string | null;
  data?: Record<string, unknown>;
}): RuntimeEvent {
  return registry.appendEvent({
    event_id: crypto.randomUUID(),
    type,
    ts: new Date().toISOString(),
    severity,
    device_id,
    data,
  });
}

export function noteTelemetry(payload: Record<string, unknown>, delivery: string): void {
  runtimeMetadata.telemetry.publishedCount += 1;
  runtimeMetadata.telemetry.lastPayload = clone(payload);
  runtimeMetadata.telemetry.lastPublishedAt = new Date().toISOString();
  runtimeMetadata.telemetry.lastDelivery = delivery;
}

export function getRuntimeSnapshot(): Record<string, unknown> {
  return clone({
    startedAt: runtimeMetadata.startedAt,
    status: runtimeMetadata.status,
    activeConfigs,
    devices: getDeviceMap(),
    telemetry: runtimeMetadata.telemetry,
    mqtt: runtimeMetadata.mqtt,
    lastError: runtimeMetadata.lastError,
  });
}

export function getRecentEvents(limit = 50): RuntimeEvent[] {
  return clone(registry.recentEvents.slice(-limit).reverse());
}

export function getActiveConfigs(): ActiveConfig[] {
  return clone(Object.values(activeConfigs));
}

export function getActiveConfig(deviceId: string): ActiveConfig | null {
  return activeConfigs[deviceId] ? clone(activeConfigs[deviceId]) : null;
}

export function getHealthSummary(): {
  runtimeStatus: string;
  mqttConnected: boolean;
  configuredDevices: number;
  connectedDevices: number;
  devicesWithCurrentFix: number;
  devicesWithStaleFix: number;
  lastError: RuntimeErrorSnapshot | null;
} {
  const devices = Object.values(getDeviceMap());
  return {
    runtimeStatus: runtimeMetadata.status,
    mqttConnected: runtimeMetadata.mqtt.connected,
    configuredDevices: Object.keys(activeConfigs).length,
    connectedDevices: devices.filter((device) => device.connected).length,
    devicesWithCurrentFix: devices.filter((device) => device.fix_details.signal_state === "fixed").length,
    devicesWithStaleFix: devices.filter((device) => device.fix_details.signal_state === "stale").length,
    lastError: runtimeMetadata.lastError,
  };
}

export function getDiagnosticsSummary(): Record<string, unknown> {
  return {
    configuredDeviceIds: Object.keys(activeConfigs).sort(),
    runtimeSnapshot: getRuntimeSnapshot(),
  };
}

export function resetRuntimeForTests(): void {
  for (const key of Object.keys(activeConfigs)) {
    delete activeConfigs[key];
  }
  registry.entries.clear();
  registry.stateSnapshots.clear();
  registry.recentEvents.length = 0;

  runtimeMetadata.status = "starting";
  runtimeMetadata.telemetry.publishedCount = 0;
  runtimeMetadata.telemetry.lastPayload = null;
  runtimeMetadata.telemetry.lastPublishedAt = null;
  runtimeMetadata.telemetry.lastDelivery = "idle";
  runtimeMetadata.mqtt.connected = false;
  runtimeMetadata.lastError = null;

  runtimeContext.auth.update({
    containerId: process.env.PIPHI_CONTAINER_ID ?? null,
    internalToken: process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? null,
  });
  runtimeContext.processState.coreBaseUrl = process.env.PIPHI_CORE_BASE_URL || "http://127.0.0.1:8000";
  runtimeContext.processState.setCurrentGeneration(null);
}
