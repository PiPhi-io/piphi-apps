import crypto from "node:crypto";
import { RuntimeContext, RuntimeRegistry, } from "piphi-runtime-kit-node";
const MAX_RUNTIME_EVENTS = 100;
function createDefaultFixDetails() {
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
function createDefaultDeviceState(deviceId, path = null) {
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
const registry = new RuntimeRegistry(MAX_RUNTIME_EVENTS);
const activeConfigs = {};
const runtimeMetadata = {
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
function clone(value) {
    return JSON.parse(JSON.stringify(value));
}
function getDeviceMap() {
    const devices = {};
    for (const deviceId of registry.ids()) {
        const device = registry.get(deviceId);
        if (device) {
            devices[deviceId] = clone(device);
        }
    }
    return devices;
}
export function getRuntimeContext() {
    return runtimeContext;
}
export function getRuntimeRegistry() {
    return registry;
}
export function setRuntimeStatus(status) {
    runtimeMetadata.status = status;
}
export function setMqttStatus(connected) {
    runtimeMetadata.mqtt.connected = Boolean(connected);
}
export function setRuntimeError(error) {
    runtimeMetadata.lastError = {
        message: error instanceof Error ? error.message : String(error),
        ts: new Date().toISOString(),
    };
}
export function clearRuntimeError() {
    runtimeMetadata.lastError = null;
}
export function upsertActiveConfig(config) {
    const deviceId = config.deviceId || config.id || config.path;
    if (!deviceId) {
        throw new Error("A device id, id, or path is required to upsert an active config");
    }
    const activeConfig = {
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
export function removeActiveConfig(deviceId) {
    delete activeConfigs[deviceId];
    if (Object.keys(activeConfigs).length === 0) {
        runtimeMetadata.status = "idle";
    }
}
export function updateDeviceRuntime(deviceId, patch) {
    const patchPath = typeof patch.path === "string" || patch.path === null ? patch.path : null;
    const existingDevice = registry.get(deviceId) ?? createDefaultDeviceState(deviceId, patchPath);
    const updatedDevice = {
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
export function recordRuntimeEvent({ type, severity = "info", device_id = null, data = {}, }) {
    return registry.appendEvent({
        event_id: crypto.randomUUID(),
        type,
        ts: new Date().toISOString(),
        severity,
        device_id,
        data,
    });
}
export function noteTelemetry(payload, delivery) {
    runtimeMetadata.telemetry.publishedCount += 1;
    runtimeMetadata.telemetry.lastPayload = clone(payload);
    runtimeMetadata.telemetry.lastPublishedAt = new Date().toISOString();
    runtimeMetadata.telemetry.lastDelivery = delivery;
}
export function getRuntimeSnapshot() {
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
export function getRecentEvents(limit = 50) {
    return clone(registry.recentEvents.slice(-limit).reverse());
}
export function getActiveConfigs() {
    return clone(Object.values(activeConfigs));
}
export function getActiveConfig(deviceId) {
    return activeConfigs[deviceId] ? clone(activeConfigs[deviceId]) : null;
}
export function getHealthSummary() {
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
export function getDiagnosticsSummary() {
    return {
        configuredDeviceIds: Object.keys(activeConfigs).sort(),
        runtimeSnapshot: getRuntimeSnapshot(),
    };
}
export function resetRuntimeForTests() {
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
