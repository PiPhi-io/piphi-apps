import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { buildConfigPayload, buildEventPayload, buildRuntimeHeaders, } from "piphi-runtime-testkit-node";
import { app } from "../server.js";
import { recordRuntimeEvent, resetRuntimeForTests, updateDeviceRuntime, upsertActiveConfig, } from "../lib/runtime.js";
async function startServer() {
    const server = await new Promise((resolve) => {
        const started = app.listen(0, "127.0.0.1", () => resolve(started));
    });
    const address = server.address();
    if (!address || typeof address === "string") {
        throw new Error("Failed to resolve test server address");
    }
    return {
        baseUrl: `http://127.0.0.1:${address.port}`,
        close: () => new Promise((resolve, reject) => {
            server.closeAllConnections();
            server.close((error) => {
                if (error) {
                    reject(error);
                    return;
                }
                resolve();
            });
        }),
    };
}
afterEach(() => {
    resetRuntimeForTests();
});
test("health route reports configured and connected GPS devices", async () => {
    const server = await startServer();
    try {
        const config = buildConfigPayload({
            id: "gps-device-1",
            containerId: "container-health-1",
            deviceId: "gps-device-1",
        });
        upsertActiveConfig({
            deviceId: String(config.deviceId),
            path: "/dev/ttyUSB0",
            containerId: config.containerId ?? null,
            configName: "Vehicle GPS",
        });
        updateDeviceRuntime(String(config.deviceId), {
            path: "/dev/ttyUSB0",
            connected: true,
            fix_status: "valid",
            fix_details: {
                signal_state: "fixed",
                fix_quality: "strong",
                position_source: "gga",
            },
        });
        const response = await fetch(`${server.baseUrl}/health/`, {
            headers: buildRuntimeHeaders({ containerId: "container-health-1" }),
        });
        assert.equal(response.status, 200);
        const body = (await response.json());
        assert.equal(body.ok, true);
        assert.equal(body.metadata.configured_devices, 1);
        assert.equal(body.metadata.connected_devices, 1);
        assert.equal(body.metadata.devices_with_current_fix, 1);
        assert.equal(body.metadata.runtime_status, "configured");
    }
    finally {
        await server.close();
    }
});
test("events route respects limit and returns most recent events first", async () => {
    const server = await startServer();
    try {
        for (const eventType of ["gps.one", "gps.two", "gps.three"]) {
            const event = buildEventPayload({
                eventType,
                deviceId: "gps-device-events",
                configId: "gps-device-events",
                containerId: "container-events-1",
                integrationId: "official-piphi-network-gps-integration",
                payload: { source: eventType },
            });
            assert.ok(event.eventType);
            recordRuntimeEvent({
                type: event.eventType,
                ...(event.severity ? { severity: event.severity } : {}),
                ...(event.deviceId !== undefined ? { device_id: event.deviceId ?? null } : {}),
                ...(event.payload ? { data: event.payload } : {}),
            });
        }
        const response = await fetch(`${server.baseUrl}/events?limit=2`);
        assert.equal(response.status, 200);
        const body = (await response.json());
        assert.equal(body.events.length, 2);
        assert.equal(body.events[0]?.type, "gps.three");
        assert.equal(body.events[1]?.type, "gps.two");
    }
    finally {
        await server.close();
    }
});
test("config route rejects payloads without a device path", async () => {
    const server = await startServer();
    try {
        const payload = {
            ...buildConfigPayload({
                id: "gps-config-invalid",
                containerId: "container-config-invalid",
            }),
            path: "",
        };
        const response = await fetch(`${server.baseUrl}/config`, {
            method: "POST",
            headers: {
                "content-type": "application/json",
                ...buildRuntimeHeaders({ containerId: "container-config-invalid" }),
            },
            body: JSON.stringify(payload),
        });
        assert.equal(response.status, 400);
        const body = (await response.json());
        assert.equal(body.errors[0]?.msg, "Please select a device before continuing");
    }
    finally {
        await server.close();
    }
});
test("deconfigure route safely reports missing GPS devices", async () => {
    const server = await startServer();
    try {
        const config = buildConfigPayload({
            id: "gps-missing",
            deviceId: "gps-missing",
        });
        const response = await fetch(`${server.baseUrl}/deconfigure`, {
            method: "POST",
            headers: {
                "content-type": "application/json",
                ...buildRuntimeHeaders(),
            },
            body: JSON.stringify({
                id: config.id,
                config: {
                    id: config.id,
                    path: "/dev/ttyMissing",
                },
            }),
        });
        assert.equal(response.status, 200);
        const body = (await response.json());
        assert.equal(body.ok, true);
        assert.equal(body.removed, false);
        assert.equal(body.removed_count, 0);
    }
    finally {
        await server.close();
    }
});
