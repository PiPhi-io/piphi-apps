import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

import { createApp } from "../src/app.js";
import { ConfigStore } from "../src/config-store.js";
import { CoreClient } from "../src/core-client.js";
import { Reconciler } from "../src/reconciler.js";
import { SidecarClient } from "../src/sidecar-client.js";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { while (cleanups.length) await cleanups.pop()?.(); });

test("projects an authenticated On/Off snapshot, persists aliases, and forwards commands", async () => {
  const sidecar = await startSidecar();
  const directory = await mkdtemp(join(tmpdir(), "piphi-matter-parent-"));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const client = new SidecarClient(sidecar.url, "sidecar-secret");
  const configs = new ConfigStore(join(directory, "config.json"));
  const reconciler = new Reconciler(client, configs, new CoreClient({}), 60_000);
  const app = createApp(reconciler, client, configs, { allowUnauthenticatedForTests: true, allowMutations: true });
  cleanups.push(() => app.close());
  await app.ready();

  const entities = await app.inject({ method: "GET", url: "/entities" });
  assert.equal(entities.statusCode, 200);
  assert.deepEqual(entities.json().entities[0], {
    id: "matter:fabric-test:node-17:1",
    device_id: "matter:fabric-test:node-17",
    name: "Desk plug",
    device_class: "switch",
    capabilities: ["connected", "switch_on"],
    available_commands: ["refresh", "toggle", "turn_off", "turn_on"],
    state: { connected: true, switch_on: false },
    metadata: { controller_identity_hash: "fabric-test", node_id: "node-17", endpoint_id: 1, source: "matter_sidecar" },
  });
  assert.equal(sidecar.authorizationHeaders[0], "Bearer sidecar-secret");

  const configured = await app.inject({ method: "POST", url: "/config", payload: { node_id: "node-17", endpoint_id: 1, alias: "Coffee maker" } });
  assert.equal(configured.statusCode, 200);
  assert.equal((await app.inject({ method: "GET", url: "/entities" })).json().entities[0].name, "Coffee maker");
  assert.match(await readFile(join(directory, "config.json"), "utf8"), /Coffee maker/);

  sidecar.switchOn = true;
  const command = await app.inject({ method: "POST", url: "/command", headers: { "x-piphi-idempotency-key": "parent-turn-on" }, payload: { entity_id: "matter:fabric-test:node-17:1", command: "turn_on" } });
  assert.equal(command.statusCode, 200);
  assert.deepEqual(sidecar.commands[0], { node_id: "node-17", endpoint_id: 1, command: "turn_on", args: {} });
  assert.equal((await app.inject({ method: "GET", url: "/state" })).json().entities[0].state.switch_on, true);

  const publicConfig = (await app.inject({ method: "GET", url: "/config" })).body;
  assert.doesNotMatch(publicConfig, /sidecar-secret/);
  assert.doesNotMatch(publicConfig, new RegExp(sidecar.url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

  const diagnostics = await app.inject({ method: "GET", url: "/diagnostics" });
  assert.equal(diagnostics.statusCode, 200);
  assert.equal(diagnostics.json().schema_version, "piphi.matter.parent.diagnostics.v1");
  assert.doesNotMatch(diagnostics.body, /sidecar-secret/);
  assert.doesNotMatch(diagnostics.body, new RegExp(sidecar.url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const repairs = await app.inject({ method: "GET", url: "/repairs" });
  assert.deepEqual(repairs.json(), { schema_version: "piphi.matter.repairs.v1", issues: [] });
  const preflight = await app.inject({ method: "GET", url: "/preflight" });
  assert.equal(preflight.json().schema_version, "piphi.matter.preflight.v1");
  assert.equal(preflight.json().ready_for_on_network, true);
  assert.doesNotMatch(preflight.body, /sidecar-secret/);
  const deniedBackup = await app.inject({ method: "POST", url: "/backup/quiesce", payload: {} });
  assert.equal(deniedBackup.statusCode, 400);
  assert.equal(sidecar.backupQuiesceCount, 0);
  const quiescedBackup = await app.inject({
    method: "POST", url: "/backup/quiesce", payload: { confirmation: "quiesce-matter-controller" },
  });
  assert.equal(quiescedBackup.statusCode, 202);
  assert.equal(sidecar.backupQuiesceCount, 1);
  const resumedBackup = await app.inject({ method: "POST", url: "/backup/resume", payload: {} });
  assert.equal(resumedBackup.statusCode, 200);
  assert.equal(sidecar.backupResumeCount, 1);

  const commissionables = await app.inject({ method: "GET", url: "/commissioning/commissionables?timeout_seconds=5" });
  assert.equal(commissionables.statusCode, 200);
  assert.equal(commissionables.json().commissionables[0].instance_name, "fixture-device");
  const unsupportedBle = await app.inject({
    method: "POST",
    url: "/commissioning/code",
    payload: { setup_payload: "MT:BLE-NOT-SUPPORTED", network_only: false },
  });
  assert.equal(unsupportedBle.statusCode, 400);
  assert.equal(sidecar.commissioningBodies.length, 0);
  const commissioned = await app.inject({
    method: "POST",
    url: "/commissioning/code",
    payload: { setup_payload: "MT:WRITE-ONLY-CANARY", network_only: true },
  });
  assert.equal(commissioned.statusCode, 201);
  assert.doesNotMatch(commissioned.body, /WRITE-ONLY-CANARY/);
  assert.deepEqual(sidecar.commissioningBodies[0], { setup_payload: "MT:WRITE-ONLY-CANARY", network_only: true });
  const wifiCommissioned = await app.inject({
    method: "POST",
    url: "/commissioning/wifi",
    payload: { setup_payload: "MT:BLE-WRITE-ONLY", ssid: "Lab WiFi", credentials: "WIFI-WRITE-ONLY" },
  });
  assert.equal(wifiCommissioned.statusCode, 201, wifiCommissioned.body);
  assert.doesNotMatch(wifiCommissioned.body, /BLE-WRITE-ONLY|WIFI-WRITE-ONLY|Lab WiFi/);
  assert.deepEqual(sidecar.wifiCommissioningBodies[0], {
    setup_payload: "MT:BLE-WRITE-ONLY", ssid: "Lab WiFi", credentials: "WIFI-WRITE-ONLY",
  });
  const threadDenied = await app.inject({
    method: "POST",
    url: "/commissioning/thread",
    payload: { setup_payload: "MT:THREAD-WRITE-ONLY", operational_dataset: "a".repeat(64) },
  });
  assert.equal(threadDenied.statusCode, 410);
  assert.equal(sidecar.threadCommissioningBodies.length, 0);
  const threadCommissioned = await app.inject({
    method: "POST",
    url: "/commissioning/thread",
    payload: {
      setup_payload: "MT:THREAD-WRITE-ONLY",
      operational_dataset: "a".repeat(64),
      experimental_acknowledgement: "thread",
    },
  });
  assert.equal(threadCommissioned.statusCode, 410, threadCommissioned.body);
  assert.doesNotMatch(threadCommissioned.body, /THREAD-WRITE-ONLY|a{32}/);
  assert.equal(sidecar.threadCommissioningBodies.length, 0);

  const unconfirmed = await app.inject({ method: "POST", url: "/nodes/node-17/decommission", payload: { confirm_node_id: "wrong" } });
  assert.equal(unconfirmed.statusCode, 400);
  assert.equal(sidecar.decommissionedNodes.length, 0);
  const decommissioned = await app.inject({ method: "POST", url: "/nodes/node-17/decommission", payload: { confirm_node_id: "node-17" } });
  assert.equal(decommissioned.statusCode, 200);
  assert.deepEqual(sidecar.decommissionedNodes, ["node-17"]);
  assert.deepEqual((await app.inject({ method: "GET", url: "/entities" })).json().entities, []);
  assert.deepEqual((await app.inject({ method: "GET", url: "/config" })).json().endpoints, []);
});

test("recovers an expired stream cursor with a full snapshot before resuming", async () => {
  const sidecar = await startSidecar();
  const directory = await mkdtemp(join(tmpdir(), "piphi-matter-reconcile-"));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const client = new SidecarClient(sidecar.url, "sidecar-secret");
  const reconciler = new Reconciler(client, new ConfigStore(join(directory, "config.json")), new CoreClient({}), 60_000);
  await reconciler.start();
  cleanups.push(async () => { reconciler.stop(); });

  await reconciler.poll();
  assert.equal(reconciler.status().cursor, 1);
  sidecar.switchOn = true;
  sidecar.expireCursor = true;
  await reconciler.poll();

  assert.equal(reconciler.status().cursor, 9);
  assert.equal(reconciler.entities()[0]?.state.switch_on, true);
  assert.equal(sidecar.snapshotRequests, 2);
});

test("production Core-facing routes require the injected Runtime SDK token", async () => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousToken = process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN;
  process.env.NODE_ENV = "production";
  process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "core-parent-secret";
  try {
    const sidecar = await startSidecar();
    const directory = await mkdtemp(join(tmpdir(), "piphi-matter-auth-"));
    cleanups.push(() => rm(directory, { recursive: true, force: true }));
    const client = new SidecarClient(sidecar.url, "sidecar-secret");
    const configs = new ConfigStore(join(directory, "config.json"));
    const app = createApp(new Reconciler(client, configs, new CoreClient({}), 60_000), client, configs);
    cleanups.push(() => app.close());
    await app.ready();

    assert.equal((await app.inject({ method: "GET", url: "/health" })).statusCode, 200);
    assert.equal((await app.inject({ method: "GET", url: "/entities" })).statusCode, 401);
    assert.equal((await app.inject({
      method: "GET",
      url: "/entities",
      headers: { "x-piphi-integration-token": "core-parent-secret", "x-container-id": "matter-parent-test" },
    })).statusCode, 200);
  } finally {
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
    if (previousToken === undefined) delete process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN;
    else process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = previousToken;
  }
});

interface SidecarFixture {
  url: string;
  authorizationHeaders: Array<string | undefined>;
  commands: Array<Record<string, unknown>>;
  switchOn: boolean;
  expireCursor: boolean;
  snapshotRequests: number;
  commissioningBodies: Array<Record<string, unknown>>;
  wifiCommissioningBodies: Array<Record<string, unknown>>;
  threadCommissioningBodies: Array<Record<string, unknown>>;
  decommissionedNodes: string[];
  nodePresent: boolean;
  backupQuiesceCount: number;
  backupResumeCount: number;
}

async function startSidecar(): Promise<SidecarFixture> {
  const fixture: SidecarFixture = {
    url: "", authorizationHeaders: [], commands: [], switchOn: false, expireCursor: false, snapshotRequests: 0,
    commissioningBodies: [], wifiCommissioningBodies: [], threadCommissioningBodies: [], decommissionedNodes: [], nodePresent: true,
    backupQuiesceCount: 0, backupResumeCount: 0,
  };
  const sharedSnapshot = JSON.parse(await readFile(
    new URL("../../../../services/piphi-matter-js-sidecar/contract/snapshot-v1.json", import.meta.url),
    "utf8",
  )) as Record<string, any>;
  const server = createServer(async (request, response) => {
    fixture.authorizationHeaders.push(request.headers.authorization);
    if (request.headers.authorization !== "Bearer sidecar-secret") return json(response, 401, { error: "unauthorized" });
    const url = new URL(request.url ?? "/", "http://sidecar");
    if (url.pathname === "/v1/matter/snapshot") {
      fixture.snapshotRequests += 1;
      const snapshot = structuredClone(sharedSnapshot);
      snapshot.generated_at = new Date().toISOString();
      snapshot.stream_id = "stream-1";
      snapshot.latest_sequence = fixture.expireCursor ? 9 : 1;
      snapshot.nodes[0].node_id = "node-17";
      snapshot.nodes[0].matter_version = "1.6";
      snapshot.nodes[0].attributes = {
        "0/40/3": "Desk plug", "1/29/0": [{ deviceType: 0x010a }], "1/29/1": [6], "1/6/0": fixture.switchOn,
      };
      if (!fixture.nodePresent) snapshot.nodes = [];
      return json(response, 200, snapshot);
    }
    if (url.pathname === "/v1/matter/events") {
      return json(response, 200, {
        schema_version: "piphi.matter.events.v1", stream_id: "stream-1",
        first_sequence: fixture.expireCursor ? 9 : 1,
        latest_sequence: fixture.expireCursor ? 9 : 1,
        next_cursor: fixture.expireCursor ? 1 : 1,
        dropped_event_count: fixture.expireCursor ? 8 : 0,
        gap: fixture.expireCursor,
        events: [],
      });
    }
    if (url.pathname === "/v1/commands/invoke") {
      fixture.commands.push(await body(request));
      return json(response, 200, { ok: true });
    }
    if (url.pathname === "/v1/discovery/commissionables") {
      return json(response, 200, [{ instance_name: "fixture-device", addresses: ["192.0.2.10"] }]);
    }
    if (url.pathname === "/v1/preflight") {
      return json(response, 200, {
        schema_version: "piphi.matter.preflight.v1",
        ready_for_on_network: true,
        ready_for_ble_wifi: true,
        checks: { backend_connected: { status: "pass" }, external_ipv6: { status: "pass" } },
        supported_scope: ["ethernet", "wifi_on_network"],
      });
    }
    if (url.pathname === "/v1/admin/backup/quiesce") {
      fixture.backupQuiesceCount += 1;
      return json(response, 202, { quiesced: true });
    }
    if (url.pathname === "/v1/admin/backup/resume") {
      fixture.backupResumeCount += 1;
      return json(response, 200, { resumed: true });
    }
    if (url.pathname === "/v1/commission/code") {
      fixture.commissioningBodies.push(await body(request));
      fixture.nodePresent = true;
      return json(response, 201, { node_id: "node-17", endpoints: [] });
    }
    if (url.pathname === "/v1/commission/wifi") {
      fixture.wifiCommissioningBodies.push(await body(request));
      fixture.nodePresent = true;
      return json(response, 201, { node_id: "node-17", endpoints: [] });
    }
    if (url.pathname === "/v1/commission/thread") {
      fixture.threadCommissioningBodies.push(await body(request));
      fixture.nodePresent = true;
      return json(response, 201, { node_id: "node-17", endpoints: [] });
    }
    if (url.pathname === "/v1/nodes/node-17/decommission") {
      const payload = await body(request);
      fixture.decommissionedNodes.push(String(payload.confirm_node_id));
      fixture.nodePresent = false;
      return json(response, 200, { removed: true, node_id: "node-17" });
    }
    return json(response, 404, { error: "not_found" });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("fixture failed to listen");
  fixture.url = `http://127.0.0.1:${address.port}`;
  cleanups.push(() => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())));
  return fixture;
}

function json(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(value));
}

async function body(request: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  return JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<string, unknown>;
}
