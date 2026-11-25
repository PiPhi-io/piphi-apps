import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer, type ServerResponse } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

import { createApp } from "../src/app.js";
import { ConfigStore } from "../src/config-store.js";
import { Reconciler } from "../src/reconciler.js";
import { settingsFromEnv } from "../src/settings.js";
import { SidecarClient, SidecarRequestError } from "../src/sidecar-client.js";
import { projectNodes } from "../src/capabilities.js";
import { publicErrorCode, redact } from "../src/redaction.js";
import type { ProjectedEntity, SidecarEventPage, SidecarSnapshot } from "../src/types.js";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { while (cleanups.length) await cleanups.pop()?.(); });

const entity: ProjectedEntity = {
  id: "matter:fabric:node:1",
  device_id: "matter:fabric:node",
  name: "Switch",
  device_class: "switch",
  capabilities: ["connected", "switch_on"],
  available_commands: ["turn_on"],
  state: { connected: true, switch_on: false },
  metadata: { controller_identity_hash: "fabric", node_id: "node", endpoint_id: 1, source: "matter_sidecar" },
};

function snapshot(switchOn = false): SidecarSnapshot {
  return {
    schema_version: "piphi.matter.snapshot.v1",
    stream_id: "stream",
    latest_sequence: 4,
    dropped_event_count: 0,
    controller: { connected: true, identity_hash: "fabric" },
    nodes: [{
      node_id: "node",
      available: true,
      attributes: { "0/40/3": "Switch", "1/29/1": [6], "1/6/0": switchOn },
    }],
  };
}

test("projects only authoritative per-endpoint Matter capabilities and recursively redacts secrets", () => {
  const [entity] = projectNodes([{
    node_id: "sensor/node", available: true, attributes: {
      "0/40/3": "Combo", "1/29/0": [{ deviceType: 0x0015 }],
      "1/29/1": [6, 8, 47, 69, 1024, 1026, 1029, 1030],
      "1/6/0": true, "1/8/0": 127, "1/47/12": 150, "1/69/0": true,
      "1/1024/0": 42, "1/1026/0": 2250, "1/1029/0": 5010, "1/1030/0": 1,
    },
  }], "controller", () => "Alias");
  assert.equal(entity?.id, "matter:controller:sensor%2Fnode:1");
  assert.equal(entity?.device_class, "light");
  assert.deepEqual(entity?.state, {
    connected: true, switch_on: true, brightness_percent: 50, temperature_c: 22.5,
    humidity_percent: 50.1, battery_percent: 75, occupancy_detected: true,
    illuminance_raw: 42, contact_open: true,
  });
  const sensorOnly = projectNodes([{ node_id: "s", available: false, attributes: { "2/29/1": [1026] } }], "c", () => undefined)[0];
  assert.equal(sensorOnly?.device_class, "matter_device");
  assert.deepEqual(redact({ nested: { api_token: "canary", safe: "ok" }, list: [{ fabric_secret: "x" }] }), {
    nested: { api_token: "[REDACTED]", safe: "ok" }, list: [{ fabric_secret: "[REDACTED]" }],
  });
  assert.equal(publicErrorCode({ code: "BOUNDED_FAILURE" }), "bounded_failure");
  assert.equal(publicErrorCode(new Error("credential canary")), "internal_error");
});

test("app reports repairs and validates route edge cases", async () => {
  let status = {
    connected: false, stream_id: null as string | null, cursor: 7, last_reconciled_at: null,
    last_error: "sidecar_unavailable" as string | null, delivery_error: "core_delivery_failed" as string | null,
    entity_count: 1,
  };
  let currentEntities = [entity];
  const reconciler = {
    start: async () => undefined,
    stop: () => undefined,
    status: () => status,
    entities: () => currentEntities,
    deliverTelemetry: async () => [{ entity_id: entity.id, delivery: "not_configured" }],
    fullSnapshot: async () => undefined,
  } as unknown as Reconciler;
  const sidecar = {
    preflight: async () => { throw new Error("sidecar down"); },
    commissionables: async () => [],
    command: async () => ({ ok: true }),
  } as unknown as SidecarClient;
  const configs = {
    list: () => [],
    set: async (value: unknown) => value,
  } as unknown as ConfigStore;
  const app = createApp(reconciler, sidecar, configs, { allowUnauthenticatedForTests: true, allowMutations: true });
  cleanups.push(() => app.close());
  await app.ready();

  assert.equal((await app.inject({ method: "GET", url: "/health" })).statusCode, 503);
  assert.equal((await app.inject({ method: "POST", url: "/telemetry" })).json().results.length, 1);
  assert.equal((await app.inject({ method: "GET", url: "/events" })).json().cursor, 7);
  assert.equal((await app.inject({ method: "GET", url: "/diagnostics" })).json().entities.length, 1);
  const unavailableRepairs = (await app.inject({ method: "GET", url: "/repairs" })).json().issues;
  assert.deepEqual(unavailableRepairs.map((issue: { id: string }) => issue.id), [
    "matter_sidecar_unavailable", "matter_core_delivery_failed",
  ]);

  status = { ...status, connected: true, last_error: null, delivery_error: null };
  assert.equal((await app.inject({ method: "GET", url: "/repairs" })).json().issues[0].id, "matter_event_stream_not_initialized");
  assert.equal((await app.inject({ method: "GET", url: "/commissioning/commissionables?timeout_seconds=0" })).statusCode, 400);
  assert.equal((await app.inject({ method: "GET", url: "/commissioning/commissionables?timeout_seconds=1.5" })).statusCode, 400);
  assert.equal((await app.inject({ method: "POST", url: "/commissioning/code", payload: {} })).statusCode, 400);
  assert.equal((await app.inject({ method: "POST", url: "/config", payload: {} })).statusCode, 400);
  assert.equal((await app.inject({ method: "POST", url: "/config", payload: { node_id: "missing", endpoint_id: 1 } })).statusCode, 404);
  assert.equal((await app.inject({ method: "POST", url: "/command", payload: { command: "invalid" } })).statusCode, 400);
  assert.equal((await app.inject({ method: "POST", url: "/command", payload: { command: "turn_on" } })).statusCode, 404);
  assert.equal((await app.inject({ method: "POST", url: "/command", payload: { command: "turn_on", node_id: "node", endpoint_id: 1 } })).statusCode, 200);
  assert.equal((await app.inject({ method: "POST", url: "/command", payload: { command: "turn_off", entity_id: entity.id } })).statusCode, 422);
  currentEntities = [];
  const upstreamError = await app.inject({ method: "GET", url: "/preflight" });
  assert.equal(upstreamError.statusCode, 502);
  assert.equal(upstreamError.json().error, "internal_error");
});

test("production authorization rejects a missing token and accepts bearer credentials", async () => {
  const previousEnv = process.env.NODE_ENV;
  const previousToken = process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN;
  process.env.NODE_ENV = "production";
  delete process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN;
  const reconciler = {
    start: async () => undefined, stop: () => undefined,
    status: () => ({ connected: true }), entities: () => [],
  } as unknown as Reconciler;
  const app = createApp(reconciler, {} as SidecarClient, { list: () => [] } as unknown as ConfigStore);
  cleanups.push(async () => {
    await app.close();
    if (previousEnv === undefined) delete process.env.NODE_ENV; else process.env.NODE_ENV = previousEnv;
    if (previousToken === undefined) delete process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN;
    else process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = previousToken;
  });
  await app.ready();
  assert.equal((await app.inject({ method: "GET", url: "/entities" })).statusCode, 503);

  process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "secret";
  assert.equal((await app.inject({ method: "GET", url: "/entities", headers: { authorization: "Bearer secret" } })).statusCode, 200);
  assert.equal((await app.inject({ method: "GET", url: "/entities", headers: { authorization: "Basic secret" } })).statusCode, 401);
});

test("config store loads valid entries, ignores malformed entries, and persists scoped removals", async () => {
  const directory = await mkdtemp(join(tmpdir(), "matter-config-coverage-"));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const path = join(directory, "nested", "config.json");
  await writeFile(join(directory, "invalid.json"), "not json");
  await assert.rejects(new ConfigStore(join(directory, "invalid.json")).load(), SyntaxError);
  await rm(join(directory, "invalid.json"));

  await new ConfigStore(join(directory, "missing.json")).load();
  await import("node:fs/promises").then(({ mkdir }) => mkdir(join(directory, "nested"), { recursive: true }));
  await writeFile(path, JSON.stringify([
    { controller_identity_hash: "fabric", node_id: "node", endpoint_id: 1, enabled: true },
    { controller_identity_hash: "", node_id: "bad", endpoint_id: 2, enabled: true },
  ]));
  const store = new ConfigStore(path);
  await store.load();
  assert.equal(store.list().length, 1);
  assert.equal(store.get("fabric", "node", 1)?.enabled, true);
  assert.equal((await store.set({ controller_identity_hash: "fabric", node_id: "node", endpoint_id: 2, enabled: true, alias: "  Alias  " })).alias, "Alias");
  assert.equal(await store.removeNode("node", "other-fabric"), 0);
  assert.equal(await store.removeNode("node", "fabric"), 2);
  assert.deepEqual(JSON.parse(await readFile(path, "utf8")), []);
});

test("reconciler records startup, delivery, and polling failures and delivers telemetry", async () => {
  let snapshotValue = snapshot();
  let snapshotFailure: unknown;
  let eventsFailure: unknown;
  const sidecar = {
    snapshot: async () => { if (snapshotFailure) throw snapshotFailure; return snapshotValue; },
    events: async (): Promise<SidecarEventPage> => {
      if (eventsFailure) throw eventsFailure;
      return { schema_version: "piphi.matter.events.v1", stream_id: "stream", first_sequence: 4, latest_sequence: 4, next_cursor: 5, dropped_event_count: 0, gap: false, events: [] };
    },
  } as unknown as SidecarClient;
  const configs = { load: async () => undefined, get: () => undefined } as unknown as ConfigStore;
  let deliveryFailure: unknown = "core unavailable";
  const core = {
    telemetry: async () => { if (deliveryFailure) throw deliveryFailure; return "delivered"; },
    stateChanged: async () => "delivered",
  };
  const reconciler = new Reconciler(sidecar, configs, core as never, 60_000);
  await reconciler.fullSnapshot();
  assert.equal(reconciler.status().delivery_error, "core_delivery_failed");
  deliveryFailure = undefined;
  snapshotValue = snapshot(true);
  await reconciler.fullSnapshot();
  assert.equal(reconciler.status().delivery_error, null);
  assert.deepEqual(await reconciler.deliverTelemetry(), [{ entity_id: entity.id, delivery: "delivered" }]);
  await reconciler.poll();
  assert.equal(reconciler.status().cursor, 5);
  eventsFailure = "poll failed";
  await assert.rejects(reconciler.poll(), (error) => error === "poll failed");
  assert.equal(reconciler.status().last_error, "sidecar_unavailable");

  snapshotFailure = new Error("startup failed");
  const startup = new Reconciler(sidecar, configs, core as never, 60_000);
  await startup.start();
  assert.equal(startup.status().connected, false);
  startup.stop();
});

test("sidecar client rejects invalid contracts and HTTP failures", async () => {
  const responses = new Map<string, { status: number; value?: unknown }>([
    ["/v1/matter/snapshot", { status: 200, value: { schema_version: "wrong" } }],
    ["/v1/matter/events", { status: 200, value: { schema_version: "wrong" } }],
    ["/v1/discovery/commissionables", { status: 200, value: {} }],
    ["/v1/preflight", { status: 200, value: [] }],
    ["/v1/admin/backup/resume", { status: 204 }],
    ["/v1/commands/invoke", { status: 500, value: { error: "failed" } }],
  ]);
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://fixture");
    const configured = responses.get(url.pathname) ?? { status: 404, value: {} };
    send(response, configured.status, configured.value);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  cleanups.push(() => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const client = new SidecarClient(`http://127.0.0.1:${address.port}`, "");

  await assert.rejects(client.snapshot(), /Invalid Matter sidecar snapshot contract/);
  await assert.rejects(client.events(3), /Invalid Matter sidecar event contract/);
  await assert.rejects(client.commissionables(2), /Invalid Matter commissionables response/);
  await assert.rejects(client.preflight(), /Invalid Matter sidecar preflight contract/);
  assert.equal(await client.resumeAfterBackup(), null);
  await assert.rejects(client.command("node", 1, "turn_on"), (error) => (
    error instanceof SidecarRequestError && error.status === 500
  ));
});

test("app classifies sidecar failures without forwarding upstream bodies", async () => {
  const reconciler = {
    start: async () => undefined, stop: () => undefined,
    status: () => ({ connected: true, stream_id: "stream" }), entities: () => [],
  } as unknown as Reconciler;
  const statuses = [400, 404, 409, 422, 503, 401, 403, 500];
  let index = 0;
  const sidecar = {
    preflight: async () => { throw new SidecarRequestError(statuses[index++]!); },
  } as unknown as SidecarClient;
  const app = createApp(reconciler, sidecar, { list: () => [] } as unknown as ConfigStore, { allowUnauthenticatedForTests: true });
  cleanups.push(() => app.close());
  await app.ready();
  const expected = [
    [422, "matter_operation_rejected"],
    [404, "matter_resource_not_found"],
    [409, "matter_operation_conflict"],
    [422, "matter_operation_rejected"],
    [503, "matter_sidecar_unavailable"],
    [502, "matter_sidecar_authentication_failed"],
    [502, "matter_sidecar_authentication_failed"],
    [502, "matter_sidecar_request_failed"],
  ];
  for (const [status, code] of expected) {
    const response = await app.inject({ method: "GET", url: "/preflight" });
    assert.equal(response.statusCode, status);
    assert.deepEqual(response.json(), { ok: false, error: code });
    assert.doesNotMatch(response.body, /HTTP|setup_payload|credential/i);
  }
});

test("settings validate production credentials and normalize optional values", () => {
  assert.throws(() => settingsFromEnv({}), /SIDECAR_URL/);
  assert.throws(() => settingsFromEnv({ NODE_ENV: "production", PIPHI_MATTER_SIDECAR_URL: "http:\/\/sidecar" }), /SIDECAR_TOKEN/);
  assert.deepEqual(settingsFromEnv({
    PIPHI_MATTER_SIDECAR_URL: "http://sidecar/",
    PIPHI_INTEGRATION_INTERNAL_TOKEN: "shared",
    PIPHI_MATTER_RECONCILE_INTERVAL_MS: "bad",
    PIPHI_TELEMETRY_ENDPOINT: "http://core/telemetry",
    PIPHI_EVENTS_ENDPOINT: "http://core/events",
    PIPHI_CONTAINER_ID: "container",
    PIPHI_CONFIG_ID: "config",
  }), {
    sidecarUrl: "http://sidecar", sidecarToken: "shared", configPath: "/app/data/config.json", reconcileIntervalMs: 5000, allowMutations: false,
    telemetryEndpoint: "http://core/telemetry", eventEndpoint: "http://core/events", coreContainerId: "container",
    coreToken: "shared", coreConfigId: "config",
  });
});

test("manifest, behavior, and catalog advertise only synchronized implemented coverage", async () => {
  const root = new URL("../../", import.meta.url);
  const manifest = JSON.parse(await readFile(new URL("manifest.json", root), "utf8"));
  const behaviors = JSON.parse(await readFile(new URL("src/behaviors.json", root), "utf8"));
  const catalog = JSON.parse(await readFile(new URL("capability-catalog.json", root), "utf8"));
  const implemented = new Set(catalog.capabilities.filter((row: { status: string }) => row.status === "implemented").map((row: { id: string }) => row.id));
  const advertised = new Set(behaviors.devices.flatMap((device: { capabilities: string[] }) => device.capabilities));
  assert.deepEqual([...advertised].sort(), [...implemented].sort());
  assert.deepEqual(Object.keys(manifest.capabilities).sort(), [...implemented].sort());
  for (const row of catalog.capabilities.filter((item: { status: string }) => item.status !== "implemented")) {
    assert.equal(advertised.has(row.id), false);
  }
  assert.equal(manifest.requires.services[0].id, "piphi.service.matter-sidecar");
  assert.equal(manifest.requires.services[0].auto_install, true);
});

function send(response: ServerResponse, status: number, value?: unknown): void {
  response.writeHead(status, value === undefined ? {} : { "content-type": "application/json" });
  response.end(value === undefined ? undefined : JSON.stringify(value));
}
