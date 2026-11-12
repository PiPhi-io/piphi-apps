import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  MockCoreServer,
  buildEventPayload,
  buildTelemetryPayload,
} from "piphi-runtime-testkit-node";

import {
  emit_event,
  send_telemetry,
  setTelemetryPublisherClientForTests,
} from "../lib/common.js";
import { getRecentEvents, resetRuntimeForTests, upsertActiveConfig } from "../lib/runtime.js";

const ORIGINAL_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  setTelemetryPublisherClientForTests(null);
  resetRuntimeForTests();
});

test("send_telemetry falls back to HTTP when MQTT is unavailable", async () => {
  const mockCore = await new MockCoreServer().start();
  try {
    process.env.PIPHI_TELEMETRY_ENDPOINT = `${mockCore.baseUrl}/api/v2/integrations/telemetry`;
    process.env.PIPHI_CONTAINER_ID = "container-telemetry-http";
    process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "token-telemetry-http";
    setTelemetryPublisherClientForTests({
      connected: false,
      publish(_topic, _payload, callback) {
        callback?.(new Error("mqtt offline"));
      },
    });

    const telemetry = buildTelemetryPayload({
      deviceId: "gps-device-http",
      containerId: "container-telemetry-http",
      metrics: { latitude: 48.1173, longitude: 11.5166 },
      units: { latitude: "degrees", longitude: "degrees" },
    });

    const result = await send_telemetry({
      device_id: telemetry.deviceId,
      timestamp: "2026-04-09T12:00:00Z",
      metrics: telemetry.metrics,
      ...(telemetry.containerId !== undefined ? { container_id: telemetry.containerId ?? null } : {}),
      ...(telemetry.units ? { units: telemetry.units } : {}),
    });

    assert.equal(result.delivery, "rest_fallback");
    assert.equal(mockCore.telemetryRequests.length, 1);
    assert.deepEqual(mockCore.telemetryRequests[0]?.body, {
      device_id: "gps-device-http",
      timestamp: "2026-04-09T12:00:00Z",
      metrics: { latitude: 48.1173, longitude: 11.5166 },
      units: { latitude: "degrees", longitude: "degrees" },
    });
    assert.equal(getRecentEvents(1)[0]?.type, "telemetry_http_fallback");
  } finally {
    await mockCore.stop();
  }
});

test("send_telemetry prefers MQTT and avoids duplicate HTTP delivery", async () => {
  const mockCore = await new MockCoreServer().start();
  try {
    process.env.PIPHI_TELEMETRY_ENDPOINT = `${mockCore.baseUrl}/api/v2/integrations/telemetry`;
    setTelemetryPublisherClientForTests({
      connected: true,
      publish(_topic, _payload, callback) {
        callback?.(null);
      },
    });

    const telemetry = buildTelemetryPayload({
      deviceId: "gps-device-mqtt",
      metrics: { speed_knots: 22.4 },
      units: { speed_knots: "knots" },
    });

    const result = await send_telemetry({
      device_id: telemetry.deviceId,
      timestamp: "2026-04-09T12:30:00Z",
      metrics: telemetry.metrics,
      ...(telemetry.units ? { units: telemetry.units } : {}),
    });

    assert.equal(result.delivery, "mqtt");
    assert.equal(mockCore.telemetryRequests.length, 0);
  } finally {
    await mockCore.stop();
  }
});

test("emit_event posts runtime events to a configured Core endpoint", async () => {
  const mockCore = await new MockCoreServer().start();
  try {
    process.env.PIPHI_EVENTS_ENDPOINT = `${mockCore.baseUrl}/api/v2/events/ingest`;
    upsertActiveConfig({
      configId: "gps-config-event",
      deviceId: "gps-device-event",
      integrationId: "gps-integration",
      containerId: "gps-container-event",
    });
    const event = buildEventPayload({
      eventType: "gps_configured",
      deviceId: "gps-device-event",
      payload: { path: "/dev/ttyUSB0" },
    });
    assert.ok(event.eventType);

    const record = await emit_event({
      type: event.eventType,
      ...(event.severity ? { severity: event.severity } : {}),
      ...(event.deviceId !== undefined ? { device_id: event.deviceId ?? null } : {}),
      ...(event.payload ? { data: event.payload } : {}),
    });

    assert.equal(record.type, "gps_configured");
    assert.equal(mockCore.eventRequests.length, 1);
    assert.deepEqual(mockCore.eventRequests[0]?.body, {
      event_id: record.event_id,
      type: "gps_configured",
      ts: record.ts,
      integration_id: "gps-integration",
      config_id: "gps-config-event",
      container_id: "gps-container-event",
      severity: "info",
      device_id: "gps-device-event",
      transport: "rest",
      data: { path: "/dev/ttyUSB0" },
    });
  } finally {
    await mockCore.stop();
  }
});
