import test from "node:test";
import assert from "node:assert/strict";
import { MockCoreServer } from "piphi-runtime-testkit-node";
import { emit_event, handle_runtime_error, send_telemetry, setTelemetryPublisherClientForTests, sign_payload, } from "../lib/common.js";
import { getHealthSummary, getRecentEvents, resetRuntimeForTests, upsertActiveConfig, } from "../lib/runtime.js";
import { restoreEnv } from "./test-helpers.js";
const ORIGINAL_ENV = { ...process.env };
test.afterEach(() => {
    restoreEnv(ORIGINAL_ENV);
    setTelemetryPublisherClientForTests(null);
    resetRuntimeForTests();
});
test("sign_payload creates deterministic hashes without a secret", async () => {
    const first = await sign_payload({ hello: "world" });
    const second = await sign_payload({ hello: "world" });
    assert.equal(first, second);
});
test("sign_payload creates deterministic HMACs with a secret", async () => {
    const first = await sign_payload({ hello: "world" }, "secret");
    const second = await sign_payload({ hello: "world" }, "secret");
    assert.equal(first, second);
});
test("sign_payload changes when the secret changes", async () => {
    const first = await sign_payload({ hello: "world" }, "secret-a");
    const second = await sign_payload({ hello: "world" }, "secret-b");
    assert.notEqual(first, second);
});
test("send_telemetry records mqtt errors when no HTTP fallback is configured", async () => {
    setTelemetryPublisherClientForTests({
        connected: false,
        publish(_topic, _payload, callback) {
            callback?.(new Error("mqtt unavailable"));
        },
    });
    const result = await send_telemetry({
        device_id: "gps-mqtt-error",
        timestamp: "2026-04-09T13:00:00Z",
        metrics: { latitude: 48.1 },
    });
    assert.equal(result.delivery, "mqtt_error");
    assert.equal(getRecentEvents(1)[0]?.type, "telemetry_delivery_failed");
});
test("send_telemetry records HTTP fallback failures as delivery errors", async () => {
    const mockCore = await new MockCoreServer().start();
    try {
        mockCore.failTelemetryWithStatus(500, { ok: false });
        process.env.PIPHI_TELEMETRY_ENDPOINT = `${mockCore.baseUrl}/api/v2/integrations/telemetry`;
        process.env.PIPHI_CONTAINER_ID = "container-http-error";
        setTelemetryPublisherClientForTests({
            connected: false,
            publish(_topic, _payload, callback) {
                callback?.(new Error("mqtt unavailable"));
            },
        });
        const result = await send_telemetry({
            device_id: "gps-http-error",
            timestamp: "2026-04-09T13:10:00Z",
            metrics: { latitude: 48.1 },
        });
        assert.equal(result.delivery, "mqtt_error");
        assert.equal(getRecentEvents(1)[0]?.type, "telemetry_delivery_failed");
    }
    finally {
        await mockCore.stop();
    }
});
test("send_telemetry updates runtime health to streaming after success", async () => {
    setTelemetryPublisherClientForTests({
        connected: true,
        publish(_topic, _payload, callback) {
            callback?.(null);
        },
    });
    await send_telemetry({
        device_id: "gps-streaming",
        timestamp: "2026-04-09T13:20:00Z",
        metrics: { speed_knots: 22.4 },
    });
    assert.equal(getHealthSummary().runtimeStatus, "streaming");
});
test("emit_event records local events even without an endpoint", async () => {
    const event = await emit_event({
        type: "gps_local_only",
        device_id: "gps-local",
        data: { ok: true },
    });
    assert.equal(event.type, "gps_local_only");
    assert.equal(getRecentEvents(1)[0]?.type, "gps_local_only");
});
test("emit_event swallows HTTP endpoint failures and stores runtime errors", async () => {
    const mockCore = await new MockCoreServer().start();
    try {
        mockCore.failEventsWithStatus(500, { ok: false });
        process.env.PIPHI_EVENTS_ENDPOINT = `${mockCore.baseUrl}/api/v2/events/ingest`;
        upsertActiveConfig({
            configId: "gps-config-error",
            deviceId: "gps-event-error",
            integrationId: "gps-integration",
            containerId: "gps-container-error",
        });
        await emit_event({
            type: "gps_event_error",
            device_id: "gps-event-error",
            data: { ok: false },
        });
        assert.equal(getHealthSummary().lastError?.message, "HTTP 500");
    }
    finally {
        await mockCore.stop();
    }
});
test("handle_runtime_error stores a runtime_error event", () => {
    handle_runtime_error(new Error("gps runtime exploded"));
    const event = getRecentEvents(1)[0];
    assert.equal(event?.type, "runtime_error");
    assert.equal(event?.data.message, "gps runtime exploded");
});
test("handle_runtime_error updates the runtime error snapshot", () => {
    handle_runtime_error(new Error("gps runtime exploded"));
    assert.equal(getHealthSummary().lastError?.message, "gps runtime exploded");
});
test("telemetry fallback uses container id from payload when provided", async () => {
    const mockCore = await new MockCoreServer().start();
    try {
        process.env.PIPHI_TELEMETRY_ENDPOINT = `${mockCore.baseUrl}/api/v2/integrations/telemetry`;
        process.env.PIPHI_CONTAINER_ID = "container-from-env";
        setTelemetryPublisherClientForTests({
            connected: false,
            publish(_topic, _payload, callback) {
                callback?.(new Error("mqtt unavailable"));
            },
        });
        await send_telemetry({
            device_id: "gps-container-payload",
            container_id: "container-from-payload",
            timestamp: "2026-04-09T13:30:00Z",
            metrics: { latitude: 48.1 },
        });
        assert.equal(mockCore.telemetryRequests[0]?.headers["x-container-id"], "container-from-payload");
    }
    finally {
        await mockCore.stop();
    }
});
test("telemetry fallback uses internal token from env", async () => {
    const mockCore = await new MockCoreServer().start();
    try {
        process.env.PIPHI_TELEMETRY_ENDPOINT = `${mockCore.baseUrl}/api/v2/integrations/telemetry`;
        process.env.PIPHI_CONTAINER_ID = "container-token";
        process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "secret-token";
        setTelemetryPublisherClientForTests({
            connected: false,
            publish(_topic, _payload, callback) {
                callback?.(new Error("mqtt unavailable"));
            },
        });
        await send_telemetry({
            device_id: "gps-token",
            timestamp: "2026-04-09T13:40:00Z",
            metrics: { latitude: 48.1 },
        });
        assert.equal(mockCore.telemetryRequests[0]?.headers["x-piphi-integration-token"], "secret-token");
    }
    finally {
        await mockCore.stop();
    }
});
