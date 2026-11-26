import assert from "node:assert/strict";
import test from "node:test";

import { createApp } from "../src/app.js";
import { redact } from "../src/redaction.js";
import { setDriverSessionFactory } from "../src/state.js";
import { createMockDriverFactory } from "./helpers/mock-driver.js";

test("administration requires explicit confirmation and has bounded cleanup", async (t) => {
  setDriverSessionFactory(createMockDriverFactory());
  const app = createApp();
  t.after(() => app.close());
  const configured = await app.inject({
    method: "POST", url: "/config", payload: { id: "admin-controller", controller_path: "/dev/serial/by-id/fake" },
  });
  assert.equal(configured.statusCode, 200);

  const rejected = await app.inject({ method: "POST", url: "/v1/admin/inclusion/start", payload: {} });
  assert.equal(rejected.statusCode, 400);
  const inclusion = await app.inject({
    method: "POST", url: "/v1/admin/inclusion/start", payload: {
      confirmation: "start-secure-inclusion",
      dsk: "12345-11111-22222-33333-44444-55555-66666-77777",
      security_classes: ["s2_authenticated"], timeout_seconds: 15,
    },
  });
  assert.equal(inclusion.statusCode, 202);
  const blockedBackup = await app.inject({
    method: "POST", url: "/v1/admin/nvm/backups", payload: { confirmation: "backup-controller-nvm" },
  });
  assert.equal(blockedBackup.statusCode, 409);
  assert.equal(blockedBackup.json().error, "controller_administration_busy");
  assert.equal((await app.inject({ method: "POST", url: "/v1/admin/inclusion/stop" })).statusCode, 200);

  const backup = await app.inject({ method: "POST", url: "/v1/admin/nvm/backups", payload: { confirmation: "backup-controller-nvm" } });
  assert.equal(backup.statusCode, 201);
  const record = backup.json();
  const restore = await app.inject({
    method: "POST", url: `/v1/admin/nvm/backups/${record.id}/restore`,
    payload: { confirmation: `restore:${record.id}:${record.controller_identity_hash}` },
  });
  assert.equal(restore.statusCode, 202);
});

test("recursive redaction removes Z-Wave security material", () => {
  const output = redact({ nested: { s2_access_control_key: "canary", values: [{ dsk: "canary" }] }, safe: "visible" });
  const encoded = JSON.stringify(output);
  assert.equal(encoded.includes("canary"), false);
  assert.equal(encoded.includes("visible"), true);
});
