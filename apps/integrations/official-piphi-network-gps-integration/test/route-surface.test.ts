import test from "node:test";
import assert from "node:assert/strict";

import { buildRuntimeHeaders } from "piphi-runtime-testkit-node";

import { resetRuntimeForTests, setRuntimeError, updateDeviceRuntime, upsertActiveConfig } from "../lib/runtime.js";
import { setGPSTestHooksForTests } from "../lib/gps.js";
import { startServer } from "./test-helpers.js";

test.afterEach(() => {
  setGPSTestHooksForTests(null);
  resetRuntimeForTests();
});

test("diagnostics route returns configured ids and runtime snapshot", async () => {
  const server = await startServer();
  try {
    upsertActiveConfig({ deviceId: "gps-diagnostics", path: "/dev/ttyUSBdiag" });
    const response = await fetch(`${server.baseUrl}/diagnostics`);
    const body = (await response.json()) as {
      ok: boolean;
      diagnostics: { configuredDeviceIds: string[]; runtimeSnapshot: Record<string, unknown> };
    };
    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.deepEqual(body.diagnostics.configuredDeviceIds, ["gps-diagnostics"]);
    assert.ok(body.diagnostics.runtimeSnapshot);
  } finally {
    await server.close();
  }
});

test("state route returns empty devices before configuration", async () => {
  const server = await startServer();
  try {
    const response = await fetch(`${server.baseUrl}/state`);
    const body = (await response.json()) as {
      status: string;
      devices: Record<string, unknown>;
      active_configs: unknown[];
    };
    assert.equal(body.status, "starting");
    assert.deepEqual(body.devices, {});
    assert.deepEqual(body.active_configs, []);
  } finally {
    await server.close();
  }
});

test("config sync accepts an empty authoritative snapshot", async () => {
  const server = await startServer();
  try {
    const response = await fetch(`${server.baseUrl}/config/sync`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...buildRuntimeHeaders({ containerId: "gps-sync-container" }),
      },
      body: JSON.stringify({
        container_id: "gps-sync-container",
        integration_id: "official-usb-gps-integration",
        generation: 4,
        configs: [],
      }),
    });
    const body = (await response.json()) as {
      ok: boolean;
      appliedConfigIds: string[];
      removedConfigIds: string[];
      generation: number | null;
    };

    assert.equal(response.status, 200);
    assert.equal(body.ok, true);
    assert.deepEqual(body.appliedConfigIds, []);
    assert.deepEqual(body.removedConfigIds, []);
    assert.equal(body.generation, 4);
  } finally {
    await server.close();
  }
});

test("state route returns configured devices and active configs", async () => {
  const server = await startServer();
  try {
    upsertActiveConfig({ deviceId: "gps-state", path: "/dev/ttyUSBstate", configName: "Car GPS" });
    updateDeviceRuntime("gps-state", {
      connected: true,
      fix_status: "valid",
      discovery: { path: "/dev/ttyUSBstate" },
      lastMetrics: { latitude: 48.1 },
      fix_details: { signal_state: "fixed", fix_quality: "strong", position_source: "rmc" },
    });

    const response = await fetch(`${server.baseUrl}/state`);
    const body = (await response.json()) as {
      status: string;
      devices: Record<string, { connected: boolean }>;
      active_configs: Array<{ deviceId: string }>;
    };
    assert.equal(body.status, "configured");
    assert.equal(body.devices["gps-state"]?.connected, true);
    assert.equal(body.active_configs[0]?.deviceId, "gps-state");
  } finally {
    await server.close();
  }
});

test("entities route returns empty entity lists without devices", async () => {
  const server = await startServer();
  try {
    const response = await fetch(`${server.baseUrl}/entities`);
    const body = (await response.json()) as { entities: unknown[] };
    assert.deepEqual(body.entities, []);
  } finally {
    await server.close();
  }
});

test("entities route expands configured GPS entities", async () => {
  const server = await startServer();
  try {
    upsertActiveConfig({ deviceId: "gps-entities", path: "/dev/ttyUSBentities", configName: "Boat GPS" });
    const response = await fetch(`${server.baseUrl}/entities`);
    const body = (await response.json()) as { entities: Array<{ id: string; device_id: string }> };
    assert.equal(body.entities.length, 7);
    assert.equal(body.entities[0]?.device_id, "gps-entities");
    assert.match(String(body.entities[0]?.id), /^gps-entities\./);
  } finally {
    await server.close();
  }
});

test("ui route returns empty enums when discovery finds no devices", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      getGPSDevicePaths: async () => [],
    });
    const response = await fetch(`${server.baseUrl}/ui`);
    const body = (await response.json()) as {
      schema: { properties: { path: { enum: string[]; enumNames: string[] } } };
      devices: unknown[];
    };
    assert.deepEqual(body.devices, []);
    assert.deepEqual(body.schema.properties.path.enum, []);
    assert.deepEqual(body.schema.properties.path.enumNames, []);
  } finally {
    await server.close();
  }
});

test("ui-config route returns discovered device options", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      getGPSDevicePaths: async () => [
        {
          id: "/dev/ttyUSB0",
          path: "/dev/ttyUSB0",
          name: "VK162 USB GPS",
          manufacturer: null,
          product: null,
          vendorId: null,
          productId: null,
          serialNumber: null,
          locationId: null,
          hwid: "USB VID:PID=1546:01a7",
          confidence: "confirmed",
          score: 100,
          likely_gps: true,
          detected_as: "VK162 USB GPS",
          driver_family: null,
          detection_reasons: ["known_gps_vid_pid:1546:01a7"],
        },
      ],
    });
    const response = await fetch(`${server.baseUrl}/ui-config`);
    const body = (await response.json()) as {
      schema: { properties: { path: { enum: string[]; enumNames: string[] } } };
      devices: Array<{ path: string }>;
    };
    assert.equal(body.devices[0]?.path, "/dev/ttyUSB0");
    assert.deepEqual(body.schema.properties.path.enum, ["/dev/ttyUSB0"]);
    assert.deepEqual(body.schema.properties.path.enumNames, ["VK162 USB GPS [confirmed]"]);
  } finally {
    await server.close();
  }
});

test("discover route returns hooked GPS devices", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      getGPSDevicePaths: async () => [
        {
          id: "/dev/ttyUSB1",
          path: "/dev/ttyUSB1",
          name: "GPS Dongle",
          manufacturer: null,
          product: null,
          vendorId: null,
          productId: null,
          serialNumber: null,
          locationId: null,
          hwid: "USB VID:PID=1546:01a8",
          confidence: "likely",
          score: 50,
          likely_gps: true,
          detected_as: "GPS Dongle",
          driver_family: null,
          detection_reasons: ["gps_keywords:gps"],
        },
      ],
    });
    const response = await fetch(`${server.baseUrl}/discover`);
    const body = (await response.json()) as { devices: Array<{ path: string }> };
    assert.equal(body.devices[0]?.path, "/dev/ttyUSB1");
  } finally {
    await server.close();
  }
});

test("discovery alias route returns the same devices", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      getGPSDevicePaths: async () => [
        {
          id: "/dev/ttyUSB2",
          path: "/dev/ttyUSB2",
          name: "GPS Alias",
          manufacturer: null,
          product: null,
          vendorId: null,
          productId: null,
          serialNumber: null,
          locationId: null,
          hwid: "USB VID:PID=1546:01a8",
          confidence: "possible",
          score: 25,
          likely_gps: true,
          detected_as: "GPS Alias",
          driver_family: null,
          detection_reasons: ["serial_path_pattern"],
        },
      ],
    });
    const response = await fetch(`${server.baseUrl}/discovery`);
    const body = (await response.json()) as { devices: Array<{ path: string }> };
    assert.equal(body.devices[0]?.path, "/dev/ttyUSB2");
  } finally {
    await server.close();
  }
});

test("command refresh returns 404 when no GPS device is available", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      refreshGPSDevice: async () => ({ success: false, message: "No configured GPS device found" }),
    });
    const response = await fetch(`${server.baseUrl}/command`, {
      method: "POST",
      headers: { "content-type": "application/json", ...buildRuntimeHeaders() },
      body: JSON.stringify({ command: "refresh" }),
    });
    const body = (await response.json()) as { success: boolean; message: string };
    assert.equal(response.status, 404);
    assert.equal(body.success, false);
  } finally {
    await server.close();
  }
});

test("command refresh returns success when the refresh hook succeeds", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      refreshGPSDevice: async () => ({ success: true, path: "/dev/ttyUSB3", is_open: true }),
    });
    const response = await fetch(`${server.baseUrl}/command`, {
      method: "POST",
      headers: { "content-type": "application/json", ...buildRuntimeHeaders() },
      body: JSON.stringify({ command: "refresh", path: "/dev/ttyUSB3" }),
    });
    const body = (await response.json()) as { success: boolean; path: string; is_open: boolean };
    assert.equal(response.status, 200);
    assert.equal(body.success, true);
    assert.equal(body.path, "/dev/ttyUSB3");
    assert.equal(body.is_open, true);
  } finally {
    await server.close();
  }
});

test("command rescan_devices returns hooked devices", async () => {
  const server = await startServer();
  try {
    setGPSTestHooksForTests({
      getGPSDevicePaths: async () => [
        {
          id: "/dev/ttyUSB4",
          path: "/dev/ttyUSB4",
          name: "GPS Rescan",
          manufacturer: null,
          product: null,
          vendorId: null,
          productId: null,
          serialNumber: null,
          locationId: null,
          hwid: "USB VID:PID=1546:01a7",
          confidence: "confirmed",
          score: 100,
          likely_gps: true,
          detected_as: "GPS Rescan",
          driver_family: null,
          detection_reasons: ["known_gps_vid_pid:1546:01a7"],
        },
      ],
    });
    const response = await fetch(`${server.baseUrl}/command`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "rescan_devices" }),
    });
    const body = (await response.json()) as { success: boolean; devices: Array<{ path: string }> };
    assert.equal(body.success, true);
    assert.equal(body.devices[0]?.path, "/dev/ttyUSB4");
  } finally {
    await server.close();
  }
});

test("command returns 400 for unsupported commands", async () => {
  const server = await startServer();
  try {
    const response = await fetch(`${server.baseUrl}/command`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ command: "explode" }),
    });
    const body = (await response.json()) as { success: boolean; message: string };
    assert.equal(response.status, 400);
    assert.equal(body.success, false);
    assert.equal(body.message, "Unsupported command");
  } finally {
    await server.close();
  }
});

test("health route includes last runtime errors", async () => {
  const server = await startServer();
  try {
    setRuntimeError(new Error("gps crashed"));
    const response = await fetch(`${server.baseUrl}/health/`);
    const body = (await response.json()) as { metadata: { last_error: { message: string } } };
    assert.equal(body.metadata.last_error.message, "gps crashed");
  } finally {
    await server.close();
  }
});
