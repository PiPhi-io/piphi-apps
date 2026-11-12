import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { assertBehaviorConditionsMatchTelemetry } from "piphi-runtime-testkit-node";

import { createApp } from "../src/app.js";
import behaviors from "../src/behaviors.json" with { type: "json" };
import { MatterSidecarService } from "../src/service.js";
import type { MatterSettings } from "../src/settings.js";
import type { MatterNodeSnapshot } from "../src/types.js";
import { FakeMatterBackend, sampleNode } from "./fake-backend.js";

async function fixture(nodes?: MatterNodeSnapshot[]) {
  const storageDir = await mkdtemp(join(tmpdir(), "piphi-matter-test-"));
  const settings: MatterSettings = {
    apiHost: "127.0.0.1",
    apiPort: 8710,
    backendHost: "127.0.0.1",
    backendPort: 5580,
    backendUrl: "ws://127.0.0.1:5580/ws",
    storageDir,
    manageBackend: false,
    enableBle: false,
  };
  const backend = new FakeMatterBackend(nodes);
  const service = new MatterSidecarService(backend, settings);
  const app = createApp(service);
  return { app, backend, service, storageDir };
}

test("health, discovery, configuration, telemetry, and entities share one negotiated contract", async (t) => {
  const contactNode = sampleNode("5678");
  contactNode.attributes = {
    "0/40/3": "Contact Sensor",
    "1/29/0": [{ deviceType: 0x0015, revision: 2 }],
    "1/29/1": [69],
    "1/69/0": true,
  };
  const { app } = await fixture([sampleNode(), contactNode]);
  t.after(() => app.close());
  assert.equal((await app.inject({ method: "GET", url: "/health" })).statusCode, 200);
  const discovery = await app.inject({ method: "GET", url: "/v1/devices/discover" });
  assert.equal(discovery.statusCode, 200);
  assert.deepEqual(discovery.json()[0].command_bindings, ["refresh", "toggle", "turn_off", "turn_on"]);
  const configured = await app.inject({ method: "POST", url: "/v1/configs", payload: { node_id: "1234", endpoint_id: 1, alias: "Office" } });
  assert.equal(configured.statusCode, 201);
  const configuredContact = await app.inject({
    method: "POST",
    url: "/v1/configs",
    payload: { node_id: "5678", endpoint_id: 1, alias: "Door" },
  });
  assert.equal(configuredContact.statusCode, 201);
  const telemetry = await app.inject({ method: "POST", url: "/v1/telemetry/poll" });
  assert.equal(telemetry.json()[0].state.temperature_c, 22.45);
  assertBehaviorConditionsMatchTelemetry(
    behaviors,
    telemetry.json().map((sample: { state: Record<string, unknown> }) => sample.state),
  );
  const entities = await app.inject({ method: "GET", url: "/entities" });
  assert.equal(entities.json().entities[0].name, "Office");
});

test("health reports dependency loss as degraded", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  await app.ready();
  backend.connected = false;
  const health = await app.inject({ method: "GET", url: "/health" });
  assert.equal(health.statusCode, 200);
  assert.equal(health.json().ok, false);
});

test("commissioning uses the controller-assigned node ID and auto-configures endpoints", async (t) => {
  const { app } = await fixture();
  t.after(() => app.close());
  const response = await app.inject({ method: "POST", url: "/v1/commission/code", payload: { setup_payload: "MT:TEST" } });
  assert.equal(response.statusCode, 201);
  assert.equal(response.json().node_id, "9001");
  const configs = await app.inject({ method: "GET", url: "/v1/configs" });
  assert.ok(configs.json().some((item: { node_id: string }) => item.node_id === "9001"));
});

test("credentials are write-only and arbitrary registry entries are rejected", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  const wifi = await app.inject({ method: "POST", url: "/v1/credentials/wifi", payload: { ssid: "Lab", credentials: "super-secret" } });
  assert.equal(wifi.statusCode, 204);
  assert.deepEqual(backend.wifiCredentials, { ssid: "Lab", credentials: "super-secret" });
  const diagnostics = await app.inject({ method: "GET", url: "/diagnostics" });
  assert.ok(!diagnostics.body.includes("super-secret"));
  const registry = await app.inject({ method: "POST", url: "/v1/registry", payload: { node_id: "999", endpoint_id: 1 } });
  assert.equal(registry.statusCode, 410);
});

test("commands fail closed and successful actions are routed to Matter.js", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  const denied = await app.inject({ method: "POST", url: "/v1/commands/invoke", payload: { node_id: "1234", endpoint_id: 1, command: "unlock" } });
  assert.equal(denied.statusCode, 400);
  const allowed = await app.inject({
    method: "POST",
    url: "/v1/commands/invoke",
    headers: { "x-piphi-idempotency-key": "matter-command-1" },
    payload: { node_id: "1234", endpoint_id: 1, command: "turn_off", args: {} },
  });
  assert.equal(allowed.statusCode, 200, allowed.body);
  assert.equal(backend.invocations[0]?.command, "turn_off");
  const arbitraryArgs = await app.inject({
    method: "POST",
    url: "/v1/commands/invoke",
    headers: { "x-piphi-idempotency-key": "matter-command-2" },
    payload: { node_id: "1234", endpoint_id: 1, command: "turn_on", args: { arbitrary: true } },
  });
  assert.equal(arbitraryArgs.statusCode, 422);
});

test("event queue is bounded and supports cursors", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  await app.ready();
  for (let index = 0; index < 1005; index += 1) backend.emit();
  const events = await app.inject({ method: "GET", url: "/v1/events" });
  assert.equal(events.json().events.length, 1000);
  const cursor = events.json().events[998].id;
  const after = await app.inject({ method: "GET", url: `/v1/events?after=${cursor}` });
  assert.equal(after.json().events.length, 1);
});

test("configured aliases survive a service restart", async () => {
  const first = await fixture();
  await first.app.inject({ method: "POST", url: "/v1/configs", payload: { node_id: "1234", endpoint_id: 1, alias: "Persistent alias" } });
  await first.app.close();
  const backend = new FakeMatterBackend();
  const second = createApp(new MatterSidecarService(backend, { ...first.service.settings, storageDir: first.storageDir }));
  const configs = await second.inject({ method: "GET", url: "/v1/configs" });
  assert.equal(configs.json()[0].alias, "Persistent alias");
  await second.close();
});
