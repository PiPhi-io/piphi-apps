#!/usr/bin/env node

import assert from "node:assert/strict";
import { execFileSync, type ExecFileSyncOptionsWithStringEncoding } from "node:child_process";
import { createServer } from "node:net";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const STORAGE_PATH = "/var/lib/piphi/matter";
const EXPECTED_SCHEMA_VERSION = 15;
const DEFAULT_TIMEOUT_SECONDS = 90;

interface ImageInspect {
  Config?: {
    User?: string;
    Volumes?: Record<string, unknown>;
  };
}

interface JsonObject {
  [key: string]: unknown;
}

export function parseImageInspect(stdout: string): ImageInspect {
  const parsed: unknown = JSON.parse(stdout);
  assert.ok(Array.isArray(parsed) && parsed.length === 1, "docker image inspect must return exactly one image");
  assert.ok(parsed[0] && typeof parsed[0] === "object", "docker image inspect returned an invalid image record");
  return parsed[0] as ImageInspect;
}

export function assertImageContract(inspect: ImageInspect): void {
  const user = String(inspect.Config?.User ?? "").trim().toLowerCase();
  assert.ok(user && user !== "root" && user !== "0" && user !== "0:0", `release image must declare a non-root user, got ${JSON.stringify(user)}`);
  assert.ok(inspect.Config?.Volumes?.[STORAGE_PATH] !== undefined, `release image must declare volume ${STORAGE_PATH}`);
}

export function parseJsonResponse(status: number, body: string, expectedStatus: number): JsonObject {
  assert.equal(status, expectedStatus, `HTTP response was ${status}, expected ${expectedStatus}: ${body}`);
  const parsed: unknown = JSON.parse(body || "{}");
  assert.ok(parsed && typeof parsed === "object" && !Array.isArray(parsed), "HTTP response must be a JSON object");
  return parsed as JsonObject;
}

export function assertTruthfulHealth(health: JsonObject): void {
  const service = health.service;
  assert.equal(health.ok, true, "health must report ok=true");
  assert.ok(service && typeof service === "object" && !Array.isArray(service), "health must include service diagnostics");
  const details = service as JsonObject;
  assert.equal(details.running, true, "health must report the sidecar running");
  assert.equal(details.backend_connected, true, "health must report the Matter backend connected");
}

export function assertSnapshotContract(snapshot: JsonObject): string {
  assert.equal(snapshot.schema_version, "piphi.matter.snapshot.v1", "snapshot contract version changed");
  const controller = snapshot.controller;
  assert.ok(controller && typeof controller === "object" && !Array.isArray(controller), "snapshot controller is missing");
  const details = controller as JsonObject;
  assert.equal(details.connected, true, "snapshot must report a connected controller");
  assert.equal(details.schema_version, EXPECTED_SCHEMA_VERSION, `Matter Server schema must be ${EXPECTED_SCHEMA_VERSION}`);
  assert.match(String(details.identity_hash ?? ""), /^[a-f0-9]{16}$/, "snapshot must contain the hashed controller identity");
  return String(details.identity_hash);
}

export function dockerRunArgs(input: {
  image: string;
  containerName: string;
  volumeName: string;
  token: string;
  port: number;
}): string[] {
  return [
    "run", "--detach", "--name", input.containerName,
    "--network", "host",
    "--volume", `${input.volumeName}:${STORAGE_PATH}`,
    "--env", `PORT=${input.port}`,
    "--env", `PIPHI_MATTER_SIDECAR_TOKEN=${input.token}`,
    "--env", "MATTER_DCL_OFFLINE=true",
    "--env", "MATTER_LOG_MANAGED_SERVER=false",
    input.image,
  ];
}

function docker(args: string[], check = true): string {
  const options: ExecFileSyncOptionsWithStringEncoding = { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] };
  try {
    return execFileSync("docker", args, options).trim();
  } catch (error) {
    if (!check) return "";
    const detail = error && typeof error === "object" && "stderr" in error ? String(error.stderr) : String(error);
    throw new Error(`docker ${args.join(" ")} failed: ${detail.trim()}`);
  }
}

async function allocatePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object", "failed to allocate a qualification port");
  await new Promise<void>((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()));
  return address.port;
}

async function requestJson(url: string, expectedStatus: number, token?: string): Promise<JsonObject> {
  const response = await fetch(url, {
    headers: {
      accept: "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    signal: AbortSignal.timeout(5_000),
  });
  return parseJsonResponse(response.status, await response.text(), expectedStatus);
}

async function waitForHealth(baseUrl: string, timeoutSeconds: number): Promise<JsonObject> {
  const deadline = Date.now() + timeoutSeconds * 1_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const health = await requestJson(`${baseUrl}/health`, 200);
      assertTruthfulHealth(health);
      return health;
    } catch (error) {
      lastError = error;
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
    }
  }
  throw new Error(`release image did not become truthfully healthy within ${timeoutSeconds}s: ${String(lastError)}`);
}

function stopAndRemove(containerName: string): void {
  docker(["stop", "--time", "10", containerName], false);
  docker(["rm", "--force", containerName], false);
}

function startContainer(input: Parameters<typeof dockerRunArgs>[0]): void {
  docker(dockerRunArgs(input));
}

async function qualify(image: string, timeoutSeconds: number): Promise<void> {
  assertImageContract(parseImageInspect(docker(["image", "inspect", image])));

  const port = await allocatePort();
  const suffix = `${process.pid}-${Date.now()}`;
  const containerName = `piphi-matter-image-qualification-${suffix}`;
  const volumeName = `piphi-matter-image-qualification-${suffix}`;
  const token = `qualification-${suffix}`;
  const baseUrl = `http://127.0.0.1:${port}`;
  const container = { image, containerName, volumeName, token, port };

  const cleanup = () => {
    stopAndRemove(containerName);
    docker(["volume", "rm", "--force", volumeName], false);
  };
  const interrupted = () => {
    cleanup();
    process.exit(130);
  };
  process.once("SIGINT", interrupted);
  process.once("SIGTERM", interrupted);

  docker(["volume", "create", volumeName]);
  try {
    startContainer(container);
    await waitForHealth(baseUrl, timeoutSeconds);
    await requestJson(`${baseUrl}/v1/matter/snapshot`, 401);
    const firstIdentity = assertSnapshotContract(await requestJson(`${baseUrl}/v1/matter/snapshot`, 200, token));

    stopAndRemove(containerName);
    startContainer(container);
    await waitForHealth(baseUrl, timeoutSeconds);
    const secondIdentity = assertSnapshotContract(await requestJson(`${baseUrl}/v1/matter/snapshot`, 200, token));
    assert.equal(secondIdentity, firstIdentity, "controller identity changed after recreation with the same volume");

    console.log(JSON.stringify({
      status: "passed",
      image,
      network: "host",
      volume_reused: true,
      schema_version: EXPECTED_SCHEMA_VERSION,
      controller_identity_hash: firstIdentity,
    }));
  } finally {
    process.removeListener("SIGINT", interrupted);
    process.removeListener("SIGTERM", interrupted);
    cleanup();
  }
}

function parseArgs(argv: string[]): { image: string; timeoutSeconds: number } {
  const [image, ...rest] = argv;
  if (!image || image.startsWith("-")) throw new Error("usage: qualify-release-image.ts IMAGE [--timeout-seconds N]");
  let timeoutSeconds = DEFAULT_TIMEOUT_SECONDS;
  if (rest.length > 0) {
    assert.equal(rest[0], "--timeout-seconds", `unknown argument ${rest[0]}`);
    assert.equal(rest.length, 2, "--timeout-seconds requires one value");
    timeoutSeconds = Number(rest[1]);
    assert.ok(Number.isInteger(timeoutSeconds) && timeoutSeconds > 0, "timeout must be a positive integer");
  }
  return { image, timeoutSeconds };
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath && fileURLToPath(import.meta.url) === invokedPath) {
  const args = parseArgs(process.argv.slice(2));
  qualify(args.image, args.timeoutSeconds).catch((error) => {
    console.error(`${basename(process.argv[1] ?? "qualify-release-image")}: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  });
}
