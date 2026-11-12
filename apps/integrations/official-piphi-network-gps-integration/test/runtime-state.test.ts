import test from "node:test";
import assert from "node:assert/strict";

import {
  clearRuntimeError,
  getActiveConfigs,
  getDiagnosticsSummary,
  getHealthSummary,
  getRecentEvents,
  getRuntimeContext,
  getRuntimeSnapshot,
  noteTelemetry,
  recordRuntimeEvent,
  removeActiveConfig,
  resetRuntimeForTests,
  setMqttStatus,
  setRuntimeError,
  setRuntimeStatus,
  updateDeviceRuntime,
  upsertActiveConfig,
} from "../lib/runtime.js";

test.afterEach(() => {
  resetRuntimeForTests();
});

test("upsertActiveConfig stores a configured device", () => {
  upsertActiveConfig({
    deviceId: "gps-1",
    path: "/dev/ttyUSB0",
    containerId: "container-1",
    configName: "Truck GPS",
  });
  assert.equal(getActiveConfigs().length, 1);
  assert.equal(getActiveConfigs()[0]?.deviceId, "gps-1");
});

test("upsertActiveConfig defaults config name to path", () => {
  upsertActiveConfig({
    deviceId: "gps-2",
    path: "/dev/ttyUSB1",
  });
  assert.equal(getActiveConfigs()[0]?.configName, "/dev/ttyUSB1");
});

test("upsertActiveConfig throws without any identifier", () => {
  assert.throws(() => upsertActiveConfig({}));
});

test("updateDeviceRuntime creates a new device entry", () => {
  const device = updateDeviceRuntime("gps-3", {
    path: "/dev/ttyUSB2",
    connected: true,
    fix_status: "valid",
    discovery: null,
    lastMetrics: { latitude: 48.1 },
  });
  assert.equal(device.deviceId, "gps-3");
  assert.equal(device.connected, true);
});

test("updateDeviceRuntime merges fix details instead of replacing them", () => {
  updateDeviceRuntime("gps-4", {
    path: "/dev/ttyUSB3",
    fix_details: {
      signal_state: "fixed",
      satellites: 8,
    },
  });
  const device = updateDeviceRuntime("gps-4", {
    fix_details: {
      fix_quality: "strong",
    },
  });
  assert.equal(device.fix_details.signal_state, "fixed");
  assert.equal(device.fix_details.fix_quality, "strong");
  assert.equal(device.fix_details.satellites, 8);
});

test("recordRuntimeEvent stores events in reverse chronological lookup order", () => {
  recordRuntimeEvent({ type: "first" });
  recordRuntimeEvent({ type: "second" });
  const events = getRecentEvents();
  assert.equal(events[0]?.type, "second");
  assert.equal(events[1]?.type, "first");
});

test("getRecentEvents respects limits", () => {
  recordRuntimeEvent({ type: "first" });
  recordRuntimeEvent({ type: "second" });
  recordRuntimeEvent({ type: "third" });
  const events = getRecentEvents(2);
  assert.equal(events.length, 2);
  assert.equal(events[0]?.type, "third");
  assert.equal(events[1]?.type, "second");
});

test("noteTelemetry updates telemetry metadata", () => {
  noteTelemetry({ device_id: "gps-5" }, "mqtt");
  const snapshot = getRuntimeSnapshot() as { telemetry: { publishedCount: number; lastDelivery: string } };
  assert.equal(snapshot.telemetry.publishedCount, 1);
  assert.equal(snapshot.telemetry.lastDelivery, "mqtt");
});

test("setRuntimeStatus updates runtime health summary", () => {
  setRuntimeStatus("streaming");
  assert.equal(getHealthSummary().runtimeStatus, "streaming");
});

test("setMqttStatus updates runtime health summary", () => {
  setMqttStatus(true);
  assert.equal(getHealthSummary().mqttConnected, true);
});

test("setRuntimeError updates the last error snapshot", () => {
  setRuntimeError(new Error("gps failed"));
  assert.equal(getHealthSummary().lastError?.message, "gps failed");
});

test("clearRuntimeError removes the last error snapshot", () => {
  setRuntimeError(new Error("gps failed"));
  clearRuntimeError();
  assert.equal(getHealthSummary().lastError, null);
});

test("removeActiveConfig deletes stored configs", () => {
  upsertActiveConfig({ deviceId: "gps-6", path: "/dev/ttyUSB6" });
  removeActiveConfig("gps-6");
  assert.equal(getActiveConfigs().length, 0);
});

test("removeActiveConfig sets runtime idle when the last config is removed", () => {
  upsertActiveConfig({ deviceId: "gps-7", path: "/dev/ttyUSB7" });
  removeActiveConfig("gps-7");
  assert.equal(getHealthSummary().runtimeStatus, "idle");
});

test("health summary counts connected devices", () => {
  upsertActiveConfig({ deviceId: "gps-8", path: "/dev/ttyUSB8" });
  updateDeviceRuntime("gps-8", {
    connected: true,
    fix_status: "searching",
    fix_details: { signal_state: "searching" },
  });
  assert.equal(getHealthSummary().connectedDevices, 1);
});

test("health summary counts current fixes", () => {
  upsertActiveConfig({ deviceId: "gps-9", path: "/dev/ttyUSB9" });
  updateDeviceRuntime("gps-9", {
    connected: true,
    fix_status: "valid",
    fix_details: { signal_state: "fixed" },
  });
  assert.equal(getHealthSummary().devicesWithCurrentFix, 1);
});

test("health summary counts stale fixes", () => {
  upsertActiveConfig({ deviceId: "gps-10", path: "/dev/ttyUSB10" });
  updateDeviceRuntime("gps-10", {
    connected: true,
    fix_status: "stale",
    fix_details: { signal_state: "stale" },
  });
  assert.equal(getHealthSummary().devicesWithStaleFix, 1);
});

test("diagnostics summary sorts configured device ids", () => {
  upsertActiveConfig({ deviceId: "gps-b", path: "/dev/b" });
  upsertActiveConfig({ deviceId: "gps-a", path: "/dev/a" });
  const diagnostics = getDiagnosticsSummary() as { configuredDeviceIds: string[] };
  assert.deepEqual(diagnostics.configuredDeviceIds, ["gps-a", "gps-b"]);
});

test("runtime snapshot includes active configs and devices", () => {
  upsertActiveConfig({ deviceId: "gps-11", path: "/dev/ttyUSB11" });
  updateDeviceRuntime("gps-11", {
    connected: true,
    fix_status: "valid",
    fix_details: { signal_state: "fixed" },
  });
  const snapshot = getRuntimeSnapshot() as {
    activeConfigs: Record<string, unknown>;
    devices: Record<string, unknown>;
  };
  assert.equal(Object.keys(snapshot.activeConfigs).length, 1);
  assert.equal(Object.keys(snapshot.devices).length, 1);
});

test("runtime snapshot is cloned before returning", () => {
  upsertActiveConfig({ deviceId: "gps-12", path: "/dev/ttyUSB12" });
  const snapshot = getRuntimeSnapshot() as { activeConfigs: Record<string, { configName: string }> };
  snapshot.activeConfigs["gps-12"]!.configName = "changed";
  const again = getRuntimeSnapshot() as { activeConfigs: Record<string, { configName: string }> };
  assert.notEqual(again.activeConfigs["gps-12"]?.configName, "changed");
});

test("getActiveConfigs returns a cloned array", () => {
  upsertActiveConfig({ deviceId: "gps-13", path: "/dev/ttyUSB13" });
  const configs = getActiveConfigs();
  configs[0]!.configName = "changed";
  assert.notEqual(getActiveConfigs()[0]?.configName, "changed");
});

test("runtime context starts with environment-auth defaults after reset", () => {
  process.env.PIPHI_CONTAINER_ID = "container-runtime-reset";
  process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "token-runtime-reset";
  resetRuntimeForTests();
  const context = getRuntimeContext();
  assert.equal(context.auth.containerId, "container-runtime-reset");
  assert.equal(context.auth.internalToken, "token-runtime-reset");
});

test("runtime reset clears events and telemetry counters", () => {
  recordRuntimeEvent({ type: "gps_before_reset" });
  noteTelemetry({ device_id: "gps-14" }, "mqtt");
  resetRuntimeForTests();
  assert.equal(getRecentEvents().length, 0);
  const snapshot = getRuntimeSnapshot() as { telemetry: { publishedCount: number } };
  assert.equal(snapshot.telemetry.publishedCount, 0);
});

test("updateDeviceRuntime sets updatedAt timestamps", () => {
  const device = updateDeviceRuntime("gps-15", {
    connected: false,
    fix_status: "idle",
    fix_details: { signal_state: "idle" },
  });
  assert.match(String(device.updatedAt), /^\d{4}-\d{2}-\d{2}T/);
});

test("recordRuntimeEvent defaults severity to info", () => {
  const event = recordRuntimeEvent({ type: "gps_default_severity" });
  assert.equal(event.severity, "info");
});

test("recordRuntimeEvent keeps explicit severity", () => {
  const event = recordRuntimeEvent({ type: "gps_warning", severity: "warning" });
  assert.equal(event.severity, "warning");
});

test("health summary counts configured devices independently of connectivity", () => {
  upsertActiveConfig({ deviceId: "gps-16", path: "/dev/ttyUSB16" });
  upsertActiveConfig({ deviceId: "gps-17", path: "/dev/ttyUSB17" });
  assert.equal(getHealthSummary().configuredDevices, 2);
});
