import assert from "node:assert/strict";
import test from "node:test";

import {
  assertImageContract,
  assertSnapshotContract,
  assertTruthfulHealth,
  dockerRunArgs,
  parseImageInspect,
  parseJsonResponse,
} from "../scripts/qualify-release-image.js";

test("image inspect parser enforces the non-root persistent-volume contract", () => {
  const inspect = parseImageInspect(JSON.stringify([{ Config: { User: "node", Volumes: { "/var/lib/piphi/matter": {} } } }]));
  assert.doesNotThrow(() => assertImageContract(inspect));
  assert.throws(() => assertImageContract({ Config: { User: "root", Volumes: { "/var/lib/piphi/matter": {} } } }), /non-root/);
  assert.throws(() => assertImageContract({ Config: { User: "node", Volumes: {} } }), /declare volume/);
});

test("HTTP parser rejects status drift and non-object JSON", () => {
  assert.deepEqual(parseJsonResponse(401, '{"error":"unauthorized"}', 401), { error: "unauthorized" });
  assert.throws(() => parseJsonResponse(503, '{"ok":false}', 200), /expected 200/);
  assert.throws(() => parseJsonResponse(200, "[]", 200), /JSON object/);
});

test("health validator requires real backend readiness", () => {
  assert.doesNotThrow(() => assertTruthfulHealth({ ok: true, service: { running: true, backend_connected: true } }));
  assert.throws(() => assertTruthfulHealth({ ok: true, service: { running: true, backend_connected: false } }), /backend connected/);
});

test("snapshot parser requires schema 15 and returns a hashed identity", () => {
  const snapshot = {
    schema_version: "piphi.matter.snapshot.v1",
    controller: { connected: true, schema_version: 15, identity_hash: "0123456789abcdef" },
  };
  assert.equal(assertSnapshotContract(snapshot), "0123456789abcdef");
  assert.throws(() => assertSnapshotContract({ ...snapshot, controller: { ...snapshot.controller, schema_version: 14 } }), /schema must be 15/);
  assert.throws(() => assertSnapshotContract({ ...snapshot, controller: { ...snapshot.controller, identity_hash: "fabric-secret" } }), /hashed controller identity/);
});

test("docker command uses host networking, the allocated port, token, and named volume", () => {
  const args = dockerRunArgs({ image: "piphi-matter:test", containerName: "matter-q", volumeName: "matter-state", token: "secret", port: 38171 });
  assert.deepEqual(args.slice(0, 7), ["run", "--detach", "--name", "matter-q", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m"]);
  assert.ok(args.includes("--network"));
  assert.ok(args.includes("matter-state:/var/lib/piphi/matter"));
  assert.ok(args.includes("PORT=38171"));
  assert.ok(args.includes("PIPHI_MATTER_SIDECAR_TOKEN=secret"));
  assert.equal(args.at(-1), "piphi-matter:test");
});
