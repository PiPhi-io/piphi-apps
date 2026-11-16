import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { createRequire } from "node:module";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer as createNetServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const tsxImport = createRequire(import.meta.url).resolve("tsx");

test("real parent and sidecar processes route commands, Core delivery, gaps, and stream restarts", { timeout: 45_000 }, async () => {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
  const repositoryRoot = resolve(packageRoot, "../../..");
  const sidecarRoot = join(repositoryRoot, "apps/services/piphi-matter-js-sidecar");
  const sidecarEntrypoint = join(sidecarRoot, "tests/fixtures/process-server.ts");
  const parentEntrypoint = join(packageRoot, "dist/src/main.js");
  const directory = await mkdtemp(join(tmpdir(), "piphi-matter-two-process-"));
  const sidecarPort = await freePort();
  const parentPort = await freePort();
  const core = await startCoreCapture();
  let sidecar: ChildProcess | undefined;
  let parent: ChildProcess | undefined;

  try {
    sidecar = startSidecar(sidecarRoot, sidecarEntrypoint, sidecarPort, directory, false);
    await waitForHttp(`http://127.0.0.1:${sidecarPort}/health`);
    parent = spawn(process.execPath, [parentEntrypoint], {
      cwd: packageRoot,
      stdio: ["ignore", "ignore", "inherit"],
      env: {
        ...process.env,
        NODE_ENV: "production",
        PORT: String(parentPort),
        PIPHI_MATTER_SIDECAR_URL: `http://127.0.0.1:${sidecarPort}`,
        PIPHI_MATTER_SIDECAR_TOKEN: "sidecar-process-secret",
        PIPHI_INTEGRATION_INTERNAL_TOKEN: "parent-process-secret",
        PIPHI_MATTER_CONFIG_PATH: join(directory, "parent-config.json"),
        PIPHI_MATTER_RECONCILE_INTERVAL_MS: "250",
        PIPHI_TELEMETRY_ENDPOINT: core.url,
        PIPHI_EVENTS_ENDPOINT: core.eventUrl,
        PIPHI_CONTAINER_ID: "matter-parent-process",
        PIPHI_CONFIG_ID: "matter-process-config",
      },
    });
    await waitForHttp(`http://127.0.0.1:${parentPort}/health`);

    const headers = {
      "x-piphi-integration-token": "parent-process-secret",
      "x-container-id": "matter-parent-process",
      "content-type": "application/json",
    };
    const initial = await jsonRequest(`http://127.0.0.1:${parentPort}/entities`, { headers });
    const initialEntity = initial.entities[0] as Record<string, any>;
    assert.equal(initialEntity.state.switch_on, false);
    const stableEntityId = String(initialEntity.id);
    const initialHealth = await jsonRequest(`http://127.0.0.1:${parentPort}/health`);
    const initialStreamId = String(initialHealth.reconciliation.stream_id);
    await waitFor(() => core.requests.filter((request) => request.path.endsWith("/telemetry")).length >= 1);
    assert.equal(core.requests.filter((request) => request.path.endsWith("/telemetry")).at(-1)?.body.metrics.switch_on, false);

    await jsonRequest(`http://127.0.0.1:${parentPort}/command`, {
      method: "POST",
      headers,
      body: JSON.stringify({ entity_id: stableEntityId, command: "turn_on" }),
    });
    const commanded = await jsonRequest(`http://127.0.0.1:${parentPort}/entities`, { headers });
    assert.equal(commanded.entities[0].state.switch_on, true);
    await waitFor(() => core.requests.filter((request) => request.path.endsWith("/telemetry")).length >= 2);
    const latestTelemetry = core.requests.filter((request) => request.path.endsWith("/telemetry")).at(-1)!;
    assert.equal(latestTelemetry.headers["x-container-id"], "matter-parent-process");
    assert.equal(latestTelemetry.headers["x-piphi-integration-token"], "parent-process-secret");
    assert.equal(latestTelemetry.body.metrics.switch_on, true);
    await waitFor(() => core.requests.some((request) => request.path.endsWith("/events/ingest")));
    const stateEvent = core.requests.find((request) => request.path.endsWith("/events/ingest"))!;
    assert.equal(stateEvent.body.type, "device.state_changed");
    assert.equal(stateEvent.body.configId, "matter-process-config");
    assert.equal(stateEvent.body.data.current.switch_on, true);

    await jsonRequest(`http://127.0.0.1:${sidecarPort}/test/burst`, {
      method: "POST",
      headers: { authorization: "Bearer sidecar-process-secret", "content-type": "application/json" },
      body: JSON.stringify({ switch_on: false, event_count: 1_005 }),
    });
    await waitFor(async () => {
      const entities = await jsonRequest(`http://127.0.0.1:${parentPort}/entities`, { headers });
      return entities.entities[0]?.state.switch_on === false;
    });

    await stopProcess(sidecar);
    await waitFor(async () => (await fetch(`http://127.0.0.1:${parentPort}/health`)).status === 503);
    const repairs = await jsonRequest(`http://127.0.0.1:${parentPort}/repairs`, { headers });
    assert.equal(repairs.issues[0]?.id, "matter_sidecar_unavailable");
    sidecar = startSidecar(sidecarRoot, sidecarEntrypoint, sidecarPort, directory, true);
    await waitForHttp(`http://127.0.0.1:${sidecarPort}/health`);
    await waitFor(async () => {
      const response = await fetch(`http://127.0.0.1:${parentPort}/health`);
      const health = await response.json() as any;
      return health.ok === true && health.reconciliation.stream_id !== initialStreamId;
    });
    const restarted = await jsonRequest(`http://127.0.0.1:${parentPort}/entities`, { headers });
    assert.equal(restarted.entities[0].id, stableEntityId);
    assert.equal(restarted.entities[0].state.switch_on, true);
  } finally {
    await Promise.allSettled([stopProcess(parent), stopProcess(sidecar), core.close()]);
    await rm(directory, { recursive: true, force: true });
  }
});

function startSidecar(root: string, entrypoint: string, port: number, directory: string, switchOn: boolean): ChildProcess {
  return spawn(process.execPath, ["--import", tsxImport, entrypoint], {
    cwd: root,
    stdio: ["ignore", "ignore", "inherit"],
    env: {
      ...process.env,
      NODE_ENV: "production",
      PORT: String(port),
      MATTER_STORAGE_DIR: join(directory, "sidecar-storage"),
      PIPHI_MATTER_SIDECAR_TOKEN: "sidecar-process-secret",
      TEST_SWITCH_ON: String(switchOn),
    },
  });
}

async function stopProcess(child: ChildProcess | undefined): Promise<void> {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise<void>((resolve) => child.once("exit", () => resolve())),
    new Promise<void>((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function waitForHttp(url: string): Promise<void> {
  await waitFor(async () => {
    try { return (await fetch(url)).status < 500; } catch { return false; }
  });
}

async function waitFor(check: () => boolean | Promise<boolean>, timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for process condition");
}

async function jsonRequest(url: string, init?: RequestInit): Promise<any> {
  const response = await fetch(url, init);
  const value = await response.json();
  if (!response.ok) throw new Error(`${url} returned ${response.status}: ${JSON.stringify(value)}`);
  return value;
}

async function freePort(): Promise<number> {
  const server = createNetServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Could not allocate a port");
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

async function startCoreCapture(): Promise<{
  url: string;
  eventUrl: string;
  requests: Array<{ path: string; headers: IncomingMessage["headers"]; body: any }>;
  close(): Promise<void>;
}> {
  const requests: Array<{ path: string; headers: IncomingMessage["headers"]; body: any }> = [];
  const server = createServer(async (request: IncomingMessage, response: ServerResponse) => {
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(Buffer.from(chunk));
    requests.push({ path: request.url ?? "", headers: request.headers, body: JSON.parse(Buffer.concat(chunks).toString("utf8")) });
    response.writeHead(202, { "content-type": "application/json" });
    response.end("{}");
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Core capture failed to listen");
  return {
    url: `http://127.0.0.1:${address.port}/api/v2/integrations/telemetry`,
    eventUrl: `http://127.0.0.1:${address.port}/api/v2/events/ingest`,
    requests,
    close: () => {
      server.closeAllConnections();
      return new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    },
  };
}
