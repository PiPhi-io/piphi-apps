import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createApp } from "../src/app.js";
import { MatterSidecarService } from "../src/service.js";
import type { MatterSettings } from "../src/settings.js";
import { FakeMatterBackend } from "./fake-backend.js";

async function fixture(overrides: Partial<MatterSettings> = {}) {
  const settings: MatterSettings = {
    apiHost: "127.0.0.1",
    apiPort: 8710,
    backendHost: "127.0.0.1",
    backendPort: 5580,
    backendUrl: "ws://127.0.0.1:5580/ws",
    storageDir: await mkdtemp(join(tmpdir(), "piphi-matter-routes-")),
    manageBackend: false,
    enableBle: false,
    dclOffline: false,
    logManagedServer: false,
    ...overrides,
  };
  const backend = new FakeMatterBackend();
  backend.bluetoothEnabled = settings.enableBle;
  const service = new MatterSidecarService(backend, settings);
  return {
    app: createApp(service, {
      bleBinding: "dbus",
      blePreflight: async () => ({ status: "pass", adapter: "hci0", transport: "bluez_dbus" }),
    }), backend, service,
  };
}

test("diagnostics, discovery, registry, and commissioning expose bounded public shapes", async (t) => {
  const { app, backend } = await fixture({ backendHost: "::1", enableBle: true, primaryInterface: "definitely-missing" });
  t.after(() => app.close());

  const diagnostics = await app.inject({ method: "GET", url: "/diagnostics" });
  assert.deepEqual(diagnostics.json().security, {
    backend_bound_to_loopback: true,
    ble_enabled: true,
    credentials_exposed: false,
  });

  const preflight = await app.inject({ method: "GET", url: "/v1/preflight" });
  assert.equal(preflight.json().checks.selected_interface.status, "fail");
  assert.equal(preflight.json().checks.selected_interface.mode, "explicit");
  assert.equal(preflight.json().checks.selected_interface.name, "definitely-missing");
  assert.equal(preflight.json().checks.ble_commissioning.status, "pass");
  assert.equal(preflight.json().ready_for_on_network, false);
  assert.equal(preflight.json().ready_for_ble_wifi, false);

  const discovered = await app.inject({ method: "GET", url: "/v1/devices/discover?node_id=1234" });
  assert.equal(discovered.json()[0].id, "1234:1");
  const registry = await app.inject({ method: "GET", url: "/v1/registry" });
  assert.equal(registry.json()[0].node_id, "1234");

  const originalDiscover = backend.discoverCommissionables.bind(backend);
  const timeouts: number[] = [];
  backend.discoverCommissionables = async (timeout) => {
    timeouts.push(timeout);
    return originalDiscover(timeout);
  };
  const commissionables = await app.inject({ method: "GET", url: "/v1/discovery/commissionables?timeout_seconds=61" });
  assert.equal(timeouts[0], 5);
  assert.deepEqual(commissionables.json()[0], {
    instance_name: "test-light",
    vendor_id: 4660,
    product_id: 1,
    device_type: null,
    long_discriminator: null,
    commissioning_mode: null,
    addresses: ["fd00::1"],
    metadata: {},
  });
  await app.inject({ method: "GET", url: "/v1/discovery/commissionables?timeout_seconds=60" });
  assert.deepEqual(timeouts, [5, 60]);

  const invalidCommission = await app.inject({ method: "POST", url: "/v1/commission/code", payload: {} });
  assert.equal(invalidCommission.statusCode, 400);
  assert.match(invalidCommission.json().error, /setup_payload is required/);
});

test("BLE Wi-Fi provisioning uses an isolated credential slot and always clears it", async (t) => {
  const { app, backend } = await fixture({ enableBle: true });
  t.after(() => app.close());
  backend.wifiCredentialEntries.set("piphi-provision-orphan", { ssid: "Old", credentials: "ORPHANED" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/commission/wifi",
    payload: { setup_payload: "MT:WRITE-ONLY-SETUP", ssid: "Lab WiFi", credentials: "WRITE-ONLY-PASSWORD" },
  });
  assert.equal(response.statusCode, 201, response.body);
  assert.doesNotMatch(response.body, /WRITE-ONLY|Lab WiFi/);
  assert.equal(backend.wifiCredentialEntries.size, 0);
  assert.deepEqual(backend.provisioningCalls.map(({ operation }) => operation), ["set", "commission", "clear"]);
  const ids = backend.provisioningCalls.map(({ id }) => id).filter(Boolean);
  assert.equal(new Set(ids).size, 1);
  assert.equal(backend.provisioningCalls[1]?.networkOnly, false);
});

test("BLE Wi-Fi provisioning clears temporary credentials after commissioning failure", async (t) => {
  const { app, backend } = await fixture({ enableBle: true });
  t.after(() => app.close());
  backend.commissionWithCode = async () => { throw new Error("not-discovered"); };
  const response = await app.inject({
    method: "POST", url: "/v1/commission/wifi",
    payload: { setup_payload: "MT:WRITE-ONLY", ssid: "Lab", credentials: "PASSWORD" },
  });
  assert.equal(response.statusCode, 400);
  assert.doesNotMatch(response.body, /PASSWORD|Lab/);
  assert.equal(backend.wifiCredentialEntries.size, 0);
  assert.equal(backend.provisioningCalls.at(-1)?.operation, "clear");
});

test("BLE Wi-Fi provisioning rejects disabled or invalid secret inputs before storage", async (t) => {
  const disabled = await fixture();
  const enabled = await fixture({ enableBle: true });
  t.after(() => Promise.all([disabled.app.close(), enabled.app.close()]));
  const valid = { setup_payload: "MT:VALID", ssid: "Lab", credentials: "PASSWORD" };
  assert.equal((await disabled.app.inject({ method: "POST", url: "/v1/commission/wifi", payload: valid })).statusCode, 503);
  for (const payload of [
    { ...valid, setup_payload: "" },
    { ...valid, ssid: " padded " },
    { ...valid, credentials: "" },
  ]) {
    assert.equal((await enabled.app.inject({ method: "POST", url: "/v1/commission/wifi", payload })).statusCode, 400);
  }
  assert.equal(enabled.backend.wifiCredentialEntries.size, 0);
});

test("persistent Wi-Fi credentials are rejected while other configuration routes remain bounded", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());

  for (const payload of [{}, { ssid: "   ", credentials: "secret" }, { ssid: "Lab" }]) {
    const response = await app.inject({ method: "POST", url: "/v1/credentials/wifi", payload });
    assert.equal(response.statusCode, 410);
  }
  const threadMissing = await app.inject({ method: "POST", url: "/v1/credentials/thread", payload: { operational_dataset: " " } });
  assert.equal(threadMissing.statusCode, 400);
  assert.equal((await app.inject({ method: "POST", url: "/v1/credentials/thread", payload: { operational_dataset: " dataset " } })).statusCode, 204);
  assert.equal(backend.threadDataset, "dataset");
  assert.equal((await app.inject({ method: "DELETE", url: "/v1/credentials/thread" })).statusCode, 204);
  assert.equal(backend.threadDataset, undefined);

  assert.equal(backend.wifiCredentials, undefined);
  assert.equal((await app.inject({ method: "DELETE", url: "/v1/credentials/wifi" })).statusCode, 204);
  assert.equal(backend.wifiCredentials, undefined);

  const invalidConfig = await app.inject({ method: "POST", url: "/v1/configs", payload: { node_id: "1234", endpoint_id: 1.5 } });
  assert.equal(invalidConfig.statusCode, 400);
  const configured = await app.inject({ method: "POST", url: "/v1/configs", payload: { node_id: "1234", endpoint_id: 1 } });
  assert.equal(configured.statusCode, 201);
  assert.equal((await app.inject({ method: "DELETE", url: "/v1/configs/1234/1" })).statusCode, 200);
  const missing = await app.inject({ method: "DELETE", url: "/v1/configs/1234/1" });
  assert.equal(missing.statusCode, 404);
});

test("transport events and command aliases reject invalid input and accept alternate fields", async (t) => {
  const { app, backend } = await fixture();
  t.after(() => app.close());

  for (const query of ["after=-1", "after=1.5", "limit=0", "limit=501", "limit=nope"]) {
    const response = await app.inject({ method: "GET", url: `/v1/matter/events?${query}` });
    assert.equal(response.statusCode, 400, query);
  }
  const page = await app.inject({ method: "GET", url: "/v1/matter/events?after=0&limit=1" });
  assert.equal(page.statusCode, 200);

  const missingTarget = await app.inject({ method: "POST", url: "/command", payload: { command: "refresh" } });
  assert.equal(missingTarget.statusCode, 400);
  const command = await app.inject({
    method: "POST",
    url: "/command",
    headers: { "x-piphi-idempotency-key": "alternate-command-shape" },
    payload: { command: "toggle", device_id: "1234", entity_id: 1, params: {} },
  });
  assert.equal(command.statusCode, 200, command.body);
  assert.deepEqual(backend.invocations.at(-1), {
    nodeId: "1234",
    endpointId: 1,
    command: "toggle",
    args: {},
  });
  const targeted = await app.inject({
    method: "POST",
    url: "/command",
    headers: { "x-piphi-idempotency-key": "target-command-shape" },
    payload: { command: "refresh", target: { node_id: "1234", endpoint_id: 1 } },
  });
  assert.equal(targeted.statusCode, 200, targeted.body);
});
