import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
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
    dclOffline: false,
    logManagedServer: false,
    allowControl: true,
    allowCommissioning: true,
  };
  const backend = new FakeMatterBackend(nodes);
  const service = new MatterSidecarService(backend, settings);
  const app = createApp(service, { allowUnauthenticatedForTests: true });
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
  assert.deepEqual(entities.json(), { entities: [] });
  const configs = await app.inject({ method: "GET", url: "/v1/configs" });
  assert.equal(configs.json()[0].alias, "Office");
});

test("health reports dependency loss as degraded", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  await app.ready();
  backend.connected = false;
  const health = await app.inject({ method: "GET", url: "/health" });
  assert.equal(health.statusCode, 503);
  assert.equal(health.json().ok, false);
});

test("network preflight is redacted and scoped to supported transports", async (t) => {
  const { app } = await fixture();
  t.after(() => app.close());
  const response = await app.inject({ method: "GET", url: "/v1/preflight" });
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().schema_version, "piphi.matter.preflight.v1");
  assert.deepEqual(response.json().supported_scope, ["ethernet", "wifi_on_network"]);
  assert.equal(response.json().checks.backend_connected.status, "pass");
  assert.doesNotMatch(response.body, /credentials|operational_dataset|setup_payload/i);
});

test("decommissioning is explicitly node-scoped and confirmed", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());

  const legacy = await app.inject({ method: "DELETE", url: "/v1/registry/1234/1" });
  assert.equal(legacy.statusCode, 410);
  assert.equal(backend.nodes.length, 1);

  const unconfirmed = await app.inject({
    method: "POST",
    url: "/v1/nodes/1234/decommission",
    payload: { confirm_node_id: "different-node" },
  });
  assert.equal(unconfirmed.statusCode, 400);
  assert.equal(backend.nodes.length, 1);

  const confirmed = await app.inject({
    method: "POST",
    url: "/v1/nodes/1234/decommission",
    payload: { confirm_node_id: "1234" },
  });
  assert.equal(confirmed.statusCode, 200);
  assert.equal(backend.nodes.length, 0);
});

test("backup quiescing is confirmed, idempotent, and resumable", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());

  const denied = await app.inject({ method: "POST", url: "/v1/admin/backup/quiesce", payload: {} });
  assert.equal(denied.statusCode, 400);
  assert.equal(backend.connected, true);

  const quiesced = await app.inject({
    method: "POST",
    url: "/v1/admin/backup/quiesce",
    payload: { confirmation: "quiesce-matter-controller" },
  });
  assert.equal(quiesced.statusCode, 202);
  assert.equal(backend.connected, false);
  const repeated = await app.inject({
    method: "POST",
    url: "/v1/admin/backup/quiesce",
    payload: { confirmation: "quiesce-matter-controller" },
  });
  assert.equal(repeated.json().already_quiesced, true);

  const resumed = await app.inject({ method: "POST", url: "/v1/admin/backup/resume" });
  assert.equal(resumed.statusCode, 200);
  assert.equal(backend.connected, true);
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

test("persistent Wi-Fi credentials and arbitrary registry entries are rejected", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());
  const wifi = await app.inject({ method: "POST", url: "/v1/credentials/wifi", payload: { ssid: "Lab", credentials: "super-secret" } });
  assert.equal(wifi.statusCode, 410);
  assert.equal(backend.wifiCredentials, undefined);
  const diagnostics = await app.inject({ method: "GET", url: "/diagnostics" });
  assert.ok(!diagnostics.body.includes("super-secret"));
  const registry = await app.inject({ method: "POST", url: "/v1/registry", payload: { node_id: "999", endpoint_id: 1 } });
  assert.equal(registry.statusCode, 410);
});

test("transport snapshot exposes only allow-listed Matter attributes", async (t) => {
  const node = sampleNode();
  node.attributes["0/49/0"] = "network-credentials-canary";
  node.attributes["0/62/3"] = "operational-key-canary";
  node.attributes["1/63/0"] = "group-key-canary";
  node.attributes["0/40/15"] = "serial-number-canary";
  node.attributes["0/40/18"] = "unique-id-canary";
  const { app } = await fixture([node]);
  t.after(() => app.close());

  const response = await app.inject({ method: "GET", url: "/v1/matter/snapshot" });
  assert.equal(response.statusCode, 200);
  assert.equal(response.json().schema_version, "piphi.matter.snapshot.v1");
  assert.equal(response.json().nodes[0].attributes["1/6/0"], true);
  assert.equal(response.json().nodes[0].attributes["0/40/8"], "1.0");
  assert.equal(response.json().nodes[0].attributes["0/40/10"], "1.0.0");
  assert.doesNotMatch(response.body, /canary/);
});

test("serialized snapshot matches the shared parent-sidecar wire fixture", async (t) => {
  const { app } = await fixture();
  t.after(() => app.close());

  const response = await app.inject({ method: "GET", url: "/v1/matter/snapshot" });
  assert.equal(response.statusCode, 200);
  const actual = response.json();
  actual.generated_at = "<generated-at>";
  actual.stream_id = "<stream-id>";
  const expected = JSON.parse(await readFile(new URL("../contract/snapshot-v1.json", import.meta.url), "utf8"));
  assert.deepEqual(actual, expected);
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
  assert.equal(events.json().dropped_event_count, 5);
  const cursor = events.json().events[998].id;
  const after = await app.inject({ method: "GET", url: `/v1/events?after=${cursor}` });
  assert.equal(after.json().events.length, 1);

  const expired = await app.inject({ method: "GET", url: "/v1/events?after=evicted-or-unknown" });
  assert.equal(expired.statusCode, 409);
  assert.equal(expired.json().error, "event_cursor_expired");
  assert.equal(expired.json().recovery, "fetch_full_snapshot");
});

test("command saturation applies bounded backpressure and recovers capacity", async (t) => {
  const { app, backend, service } = await fixture();
  t.after(() => app.close());
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  backend.invoke = async () => { await blocked; return { accepted: true }; };
  await app.ready();
  const running = Array.from({ length: 16 }, () => service.invoke("1234", 1, "turn_on", {}));
  await new Promise<void>((resolve) => setImmediate(resolve));
  await assert.rejects(service.invoke("1234", 1, "turn_on", {}), (error: unknown) => (
    error instanceof Error && "statusCode" in error && error.statusCode === 429
  ));
  assert.equal(service.snapshot().active_command_count, 16);
  release();
  await Promise.all(running);
  assert.equal(service.snapshot().active_command_count, 0);
});

test("configured aliases survive a service restart", async () => {
  const first = await fixture();
  await first.app.inject({ method: "POST", url: "/v1/configs", payload: { node_id: "1234", endpoint_id: 1, alias: "Persistent alias" } });
  await first.app.close();
  const backend = new FakeMatterBackend();
  const second = createApp(new MatterSidecarService(backend, { ...first.service.settings, storageDir: first.storageDir }), { allowUnauthenticatedForTests: true });
  const configs = await second.inject({ method: "GET", url: "/v1/configs" });
  assert.equal(configs.json()[0].alias, "Persistent alias");
  await second.close();
});

test("production APIs require the Core-injected bearer token", async (t) => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousToken = process.env.PIPHI_MATTER_SIDECAR_TOKEN;
  process.env.NODE_ENV = "production";
  process.env.PIPHI_MATTER_SIDECAR_TOKEN = "matter-sidecar-test-token";
  t.after(() => {
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
    if (previousToken === undefined) delete process.env.PIPHI_MATTER_SIDECAR_TOKEN;
    else process.env.PIPHI_MATTER_SIDECAR_TOKEN = previousToken;
  });

  const { app } = await fixture();
  t.after(() => app.close());
  const health = await app.inject({ method: "GET", url: "/health" });
  assert.equal(health.statusCode, 200);
  const denied = await app.inject({ method: "GET", url: "/v1/events" });
  assert.equal(denied.statusCode, 401);
  const allowed = await app.inject({
    method: "GET",
    url: "/v1/events",
    headers: { authorization: "Bearer matter-sidecar-test-token" },
  });
  assert.equal(allowed.statusCode, 200);
});
