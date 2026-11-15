import assert from "node:assert/strict";
import test from "node:test";

import { loadBrokerConfig } from "../src/config.js";
import { parseIdentityPolicy, renderIdentityAcl } from "../src/identity.js";

const config = loadBrokerConfig({ MQTT_ALLOW_PLAINTEXT: "true", MQTT_AUTH_POLICY_FILE: "/run/secrets/policy.json" });

function policy(principals: unknown[]): string {
  return JSON.stringify({ schema_version: 1, principals });
}

test("identity policy renders distinct least-privilege principals", () => {
  const parsed = parseIdentityPolicy(policy([
    { username: "worker", password_secret_file: "/run/secrets/worker", read: ["piphi/worker/#"], write: ["piphi/worker/set"], health: false },
    { username: "health", password_secret_file: "/run/secrets/health", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: true },
  ]), config);
  assert.equal(parsed.principals.length, 2);
  assert.match(renderIdentityAcl(parsed), /user worker\ntopic read piphi\/worker\/#\ntopic write piphi\/worker\/set/);
});

test("identity policy rejects duplicate users, broad topics, and missing health identity", () => {
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "same", password_secret_file: "/run/secrets/a", read: ["piphi/a/#"], write: ["piphi/a/#"], health: true },
    { username: "same", password_secret_file: "/run/secrets/b", read: ["piphi/b/#"], write: ["piphi/b/#"], health: false },
  ]), config), /Duplicate principal/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "health", password_secret_file: "/run/secrets/health", read: ["#"], write: ["piphi/_health/#"], health: true },
  ]), config), /must stay beneath/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "worker", password_secret_file: "/run/secrets/worker", read: ["piphi/worker/#"], write: ["piphi/worker/#"], health: false },
  ]), config), /exactly one health principal/);
});
