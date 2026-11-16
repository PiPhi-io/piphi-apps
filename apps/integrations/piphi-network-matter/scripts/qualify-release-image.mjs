#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { createServer as createNetServer } from "node:net";
import { basename } from "node:path";

const DATA_PATH = "/app/data";
const DEFAULT_TIMEOUT_SECONDS = 60;

function docker(args, check = true) {
  try {
    return execFileSync("docker", args, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (error) {
    if (!check) return "";
    const detail = error && typeof error === "object" && "stderr" in error
      ? String(error.stderr).trim()
      : String(error);
    throw new Error(`docker ${args.join(" ")} failed: ${detail}`);
  }
}

function inspectImage(image) {
  const records = JSON.parse(docker(["image", "inspect", image]));
  assert.ok(Array.isArray(records) && records.length === 1, "docker must inspect exactly one image");
  const record = records[0];
  const user = String(record?.Config?.User ?? "").trim().toLowerCase();
  assert.ok(user && !["root", "0", "0:0"].includes(user), `image must declare a non-root user, got ${JSON.stringify(user)}`);
  assert.ok(record?.Config?.Volumes?.[DATA_PATH] !== undefined, `image must declare ${DATA_PATH} as a volume`);
}

function runArgs({ image, name, volume, parentPort, sidecarPort, sidecarToken, coreToken }) {
  return [
    "run", "--detach", "--name", name,
    "--network", "host",
    "--volume", `${volume}:${DATA_PATH}`,
    "--env", "NODE_ENV=production",
    "--env", `PORT=${parentPort}`,
    "--env", `PIPHI_MATTER_SIDECAR_URL=http://127.0.0.1:${sidecarPort}`,
    "--env", `PIPHI_MATTER_SIDECAR_TOKEN=${sidecarToken}`,
    "--env", `PIPHI_INTEGRATION_INTERNAL_TOKEN=${coreToken}`,
    "--env", "PIPHI_MATTER_RECONCILE_INTERVAL_MS=250",
    image,
  ];
}

async function freePort() {
  const server = createNetServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object", "could not allocate a local port");
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

async function startSidecarFixture(port, token) {
  let authenticatedRequests = 0;
  const snapshot = {
    schema_version: "piphi.matter.snapshot.v1",
    stream_id: "release-qualification-stream",
    latest_sequence: 0,
    dropped_event_count: 0,
    controller: { connected: true, identity_hash: "0123456789abcdef", schema_version: 15 },
    nodes: [{
      node_id: "qualification-node",
      available: true,
      attributes: { "0/40/5": "Qualification plug", "1/29/1": [6], "1/6/0": false },
    }],
  };
  const server = createServer((request, response) => {
    if (request.headers.authorization !== `Bearer ${token}`) {
      response.writeHead(401, { "content-type": "application/json" });
      response.end('{"ok":false,"error":"unauthorized"}');
      return;
    }
    authenticatedRequests += 1;
    const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
    if (request.method === "GET" && url.pathname === "/v1/matter/snapshot") {
      sendJson(response, 200, snapshot);
      return;
    }
    if (request.method === "GET" && url.pathname === "/v1/matter/events") {
      sendJson(response, 200, {
        schema_version: "piphi.matter.events.v1",
        stream_id: snapshot.stream_id,
        first_sequence: 0,
        latest_sequence: 0,
        next_cursor: 0,
        dropped_event_count: 0,
        gap: false,
        events: [],
      });
      return;
    }
    sendJson(response, 404, { ok: false, error: "not_found" });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  return {
    authenticatedRequests: () => authenticatedRequests,
    close: () => new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  };
}

function sendJson(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

async function requestJson(url, expectedStatus, token, init = {}) {
  const response = await fetch(url, {
    ...init,
    headers: {
      accept: "application/json",
      ...(token ? { "x-piphi-integration-token": token } : {}),
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...init.headers,
    },
    signal: AbortSignal.timeout(5_000),
  });
  const text = await response.text();
  assert.equal(response.status, expectedStatus, `${url} returned ${response.status}, expected ${expectedStatus}: ${text}`);
  return JSON.parse(text || "{}");
}

async function waitForHealthy(baseUrl, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const health = await requestJson(`${baseUrl}/health`, 200);
      assert.equal(health.ok, true);
      assert.equal(health.reconciliation?.connected, true);
      assert.equal(health.reconciliation?.entity_count, 1);
      return health;
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  throw new Error(`parent image did not become healthy within ${timeoutSeconds}s: ${String(lastError)}`);
}

function stopAndRemove(name) {
  docker(["stop", "--time", "10", name], false);
  docker(["rm", "--force", name], false);
}

async function qualify(image, timeoutSeconds) {
  inspectImage(image);
  const [parentPort, sidecarPort] = await Promise.all([freePort(), freePort()]);
  assert.notEqual(parentPort, sidecarPort, "allocated ports must differ");
  const suffix = `${process.pid}-${Date.now()}`;
  const name = `piphi-matter-parent-qualification-${suffix}`;
  const volume = `piphi-matter-parent-qualification-${suffix}`;
  const sidecarToken = `sidecar-${suffix}`;
  const coreToken = `core-${suffix}`;
  const baseUrl = `http://127.0.0.1:${parentPort}`;
  const fixture = await startSidecarFixture(sidecarPort, sidecarToken);
  const input = { image, name, volume, parentPort, sidecarPort, sidecarToken, coreToken };
  const cleanup = () => {
    stopAndRemove(name);
    docker(["volume", "rm", "--force", volume], false);
  };
  const interrupted = () => {
    cleanup();
    void fixture.close().finally(() => process.exit(130));
  };
  process.once("SIGINT", interrupted);
  process.once("SIGTERM", interrupted);

  try {
    docker(["volume", "create", volume]);
    docker(runArgs(input));
    await waitForHealthy(baseUrl, timeoutSeconds);

    const networkMode = docker(["inspect", "--format", "{{.HostConfig.NetworkMode}}", name]);
    assert.equal(networkMode, "host", "qualification container must use host networking");
    const uid = Number(docker(["exec", name, "node", "-e", "process.stdout.write(String(process.getuid()))"]));
    assert.ok(Number.isInteger(uid) && uid > 0, `container process must run non-root, got uid ${uid}`);
    assert.ok(fixture.authenticatedRequests() > 0, "parent did not authenticate to the sidecar fixture");

    await requestJson(`${baseUrl}/entities`, 401);
    await requestJson(`${baseUrl}/entities`, 401, "wrong-token");
    const firstEntities = await requestJson(`${baseUrl}/entities`, 200, coreToken);
    assert.equal(firstEntities.entities?.length, 1, "fixture entity was not projected");
    const entityId = firstEntities.entities[0].id;

    await requestJson(`${baseUrl}/config`, 200, coreToken, {
      method: "POST",
      body: JSON.stringify({ node_id: "qualification-node", endpoint_id: 1, alias: "Persistent qualification alias" }),
    });
    const firstConfig = await requestJson(`${baseUrl}/config`, 200, coreToken);
    assert.equal(firstConfig.endpoints?.[0]?.alias, "Persistent qualification alias");

    stopAndRemove(name);
    docker(runArgs(input));
    await waitForHealthy(baseUrl, timeoutSeconds);
    const recreatedEntities = await requestJson(`${baseUrl}/entities`, 200, coreToken);
    const recreatedConfig = await requestJson(`${baseUrl}/config`, 200, coreToken);
    assert.equal(recreatedEntities.entities?.[0]?.id, entityId, "entity identity changed across parent recreation");
    assert.equal(recreatedEntities.entities?.[0]?.name, "Persistent qualification alias", "persisted alias was not applied after recreation");
    assert.equal(recreatedConfig.endpoints?.[0]?.alias, "Persistent qualification alias", "configuration did not survive parent recreation");

    console.log(JSON.stringify({
      status: "passed",
      image,
      runtime_uid: uid,
      network: "host",
      production_auth: true,
      sidecar_authenticated: true,
      data_volume_reused: true,
      entity_id: entityId,
    }));
  } finally {
    process.removeListener("SIGINT", interrupted);
    process.removeListener("SIGTERM", interrupted);
    cleanup();
    await fixture.close();
  }
}

function parseArgs(argv) {
  const [image, ...rest] = argv;
  if (!image || image.startsWith("-")) throw new Error("usage: qualify-release-image.mjs IMAGE [--timeout-seconds N]");
  if (rest.length === 0) return { image, timeoutSeconds: DEFAULT_TIMEOUT_SECONDS };
  assert.deepEqual(rest.slice(0, 1), ["--timeout-seconds"], `unknown argument ${rest[0]}`);
  assert.equal(rest.length, 2, "--timeout-seconds requires one value");
  const timeoutSeconds = Number(rest[1]);
  assert.ok(Number.isInteger(timeoutSeconds) && timeoutSeconds > 0, "timeout must be a positive integer");
  return { image, timeoutSeconds };
}

try {
  const args = parseArgs(process.argv.slice(2));
  await qualify(args.image, args.timeoutSeconds);
} catch (error) {
  console.error(`${basename(process.argv[1] ?? "qualify-release-image")}: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
