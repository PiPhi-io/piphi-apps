import assert from "node:assert/strict";
import { fork, type ChildProcess } from "node:child_process";
import { cp, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { networkInterfaces, tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createApp } from "../src/app.js";
import { MatterJsBackend } from "../src/matterjs-backend.js";
import { MatterSidecarService } from "../src/service.js";
import type { MatterSettings } from "../src/settings.js";

const enabled = process.env.MATTER_E2E === "1";

test("commissions and controls a real virtual Matter On/Off light", { skip: !enabled, timeout: 240_000 }, async () => {
  const workspace = await mkdtemp(join(tmpdir(), "piphi-matter-virtual-e2e-"));
  const deviceStorage = join(workspace, "device");
  const controllerStorage = join(workspace, "controller");
  const controllerBackup = join(workspace, "controller-backup");
  const restoredControllerStorage = join(workspace, "controller-restored");
  const previousTestNetDcl = process.env.ENABLE_TEST_NET_DCL;
  const primaryInterface = externalIpv6Interface();
  process.env.ENABLE_TEST_NET_DCL = "true";
  let device: ChildProcess | undefined;
  let app: ReturnType<typeof createApp> | undefined;

  try {
    device = fork(new URL("./fixtures/virtual-onoff-light.ts", import.meta.url), [], {
      execArgv: ["--import", "tsx"],
      stdio: ["ignore", "ignore", "inherit", "ipc"],
      env: {
        ...process.env,
        MATTER_STORAGE_PATH: deviceStorage,
        MATTER_STORAGE_CLEAR: "1",
        MATTER_LOG_LEVEL: "warn",
        MATTER_MDNS_NETWORKINTERFACE: primaryInterface,
      },
    });
    const ready = await waitForMessage(device, (message) => message.type === "ready");
    assert.match(String(ready.qrPairingCode), /^MT:/);

    const backendPort = await freePort();
    const settings: MatterSettings = {
      apiHost: "127.0.0.1",
      apiPort: 8710,
      backendHost: "127.0.0.1",
      backendPort,
      backendUrl: `ws://127.0.0.1:${backendPort}/ws`,
      storageDir: controllerStorage,
      manageBackend: true,
      enableBle: false,
      dclOffline: true,
      logManagedServer: process.env.MATTER_E2E_LOGS === "1",
      primaryInterface,
    };
    let backend = new MatterJsBackend(settings);
    const service = new MatterSidecarService(backend, settings);
    app = createApp(service);
    await app.ready();
    const preflight = await app.inject({ method: "GET", url: "/v1/preflight" });
    assert.equal(preflight.statusCode, 200);
    assert.equal(preflight.json().ready_for_on_network, true, preflight.body);
    assert.equal(preflight.json().checks.selected_interface.name, primaryInterface);

    const commissioned = await app.inject({
      method: "POST",
      url: "/v1/commission/code",
      payload: { setup_payload: ready.qrPairingCode, network_only: true },
    });
    assert.equal(commissioned.statusCode, 201, commissioned.body);
    const nodeId = String(commissioned.json().node_id);
    const endpoint = commissioned.json().endpoints.find((item: Record<string, unknown>) => (
      Array.isArray(item.capabilities) && item.capabilities.includes("switch_on")
    ));
    assert.ok(endpoint, commissioned.body);
    assert.ok(endpoint.command_bindings.includes("turn_on"));
    const endpointId = Number(endpoint.endpoint_id);

    const before = await app.inject({ method: "GET", url: "/v1/matter/snapshot" });
    const cursor = Number(before.json().latest_sequence);
    const controllerIdentityHash = String(before.json().controller.identity_hash);
    const onOffChanged = waitForMessage(device, (message) => message.type === "onoff" && message.value === true);
    const command = await app.inject({
      method: "POST",
      url: "/v1/commands/invoke",
      payload: { node_id: nodeId, endpoint_id: endpointId, command: "turn_on", args: {} },
    });
    assert.equal(command.statusCode, 200, command.body);
    await onOffChanged;
    await waitFor(async () => {
      const snapshot = await app!.inject({ method: "GET", url: "/v1/matter/snapshot" });
      return snapshot.json().nodes[0]?.attributes[`${endpointId}/6/0`] === true;
    });
    const events = await app.inject({ method: "GET", url: `/v1/matter/events?after=${cursor}&limit=500` });
    assert.equal(events.statusCode, 200);
    assert.ok(events.json().events.some((event: Record<string, any>) => (
      event.type === "device.state_changed"
      && event.node_id === nodeId
      && event.endpoint_id === endpointId
      && event.payload?.value === true
    )));

    const quiesced = await app.inject({
      method: "POST",
      url: "/v1/admin/backup/quiesce",
      payload: { confirmation: "quiesce-matter-controller" },
    });
    assert.equal(quiesced.statusCode, 202);
    await copyControllerStorage(controllerStorage, controllerBackup);
    await app.close();

    await mkdir(restoredControllerStorage, { mode: 0o700 });
    await copyControllerStorage(controllerBackup, restoredControllerStorage);
    const restoredBackendPort = await freePort();
    const restoredSettings: MatterSettings = {
      ...settings,
      backendPort: restoredBackendPort,
      backendUrl: `ws://127.0.0.1:${restoredBackendPort}/ws`,
      storageDir: restoredControllerStorage,
    };
    backend = new MatterJsBackend(restoredSettings);
    app = createApp(new MatterSidecarService(backend, restoredSettings));
    await app.ready();
    await waitFor(async () => {
      const snapshot = await app!.inject({ method: "GET", url: "/v1/matter/snapshot" });
      return snapshot.json().controller.identity_hash === controllerIdentityHash
        && snapshot.json().nodes[0]?.node_id === nodeId
        && snapshot.json().nodes[0]?.available === true;
    }, 60_000);

    const onOffRestored = waitForMessage(device, (message) => message.type === "onoff" && message.value === false);
    const restoredCommand = await app.inject({
      method: "POST",
      url: "/v1/commands/invoke",
      payload: { node_id: nodeId, endpoint_id: endpointId, command: "turn_off", args: {} },
    });
    assert.equal(restoredCommand.statusCode, 200, restoredCommand.body);
    await onOffRestored;

    const decommissioned = waitForMessage(device, (message) => message.type === "decommissioned");
    const removed = await app.inject({
      method: "POST",
      url: `/v1/nodes/${encodeURIComponent(nodeId)}/decommission`,
      payload: { confirm_node_id: nodeId },
    });
    assert.equal(removed.statusCode, 200, removed.body);
    await decommissioned;
    const finalSnapshot = await app.inject({ method: "GET", url: "/v1/matter/snapshot" });
    assert.deepEqual(finalSnapshot.json().nodes, []);
  } finally {
    await app?.close();
    await stopProcess(device);
    if (previousTestNetDcl === undefined) delete process.env.ENABLE_TEST_NET_DCL;
    else process.env.ENABLE_TEST_NET_DCL = previousTestNetDcl;
    await rm(workspace, { recursive: true, force: true });
  }
});

async function waitForMessage(
  child: ChildProcess,
  predicate: (message: Record<string, any>) => boolean,
  timeoutMs = 60_000,
): Promise<Record<string, any>> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => finish(new Error("Timed out waiting for virtual Matter device")), timeoutMs);
    const onMessage = (message: Record<string, any>) => {
      if (predicate(message)) finish(undefined, message);
    };
    const onExit = (code: number | null, signal: NodeJS.Signals | null) => {
      finish(new Error(`Virtual Matter device exited before readiness (${code ?? signal})`));
    };
    const finish = (error?: Error, message?: Record<string, any>) => {
      clearTimeout(timeout);
      child.off("message", onMessage);
      child.off("exit", onExit);
      if (error) reject(error);
      else resolve(message!);
    };
    child.on("message", onMessage);
    child.once("exit", onExit);
  });
}

async function waitFor(check: () => boolean | Promise<boolean>, timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("Timed out waiting for Matter state convergence");
}

async function stopProcess(child: ChildProcess | undefined): Promise<void> {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise<void>((resolve) => child.once("exit", () => resolve())),
    new Promise<void>((resolve) => setTimeout(resolve, 10_000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function freePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

async function copyControllerStorage(source: string, target: string): Promise<void> {
  await mkdir(target, { recursive: true, mode: 0o700 });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (entry.name === ".piphi-controller.lock") continue;
    await cp(join(source, entry.name), join(target, entry.name), {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
  }
}

function externalIpv6Interface(): string {
  for (const [name, addresses] of Object.entries(networkInterfaces())) {
    if (addresses?.some((address) => !address.internal && address.family === "IPv6")) return name;
  }
  throw new Error("Virtual Matter qualification requires a non-loopback IPv6 interface");
}
