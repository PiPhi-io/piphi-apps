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
    { username: "worker", namespace: "worker", password_secret_file: "/run/secrets/worker", read: ["piphi/worker/#"], write: ["piphi/worker/set"], health: false },
    { username: "health", namespace: "_health", password_secret_file: "/run/secrets/health", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: true },
  ]), config);
  assert.equal(parsed.principals.length, 2);
  assert.match(renderIdentityAcl(parsed), /user worker[\s\S]*topic read piphi\/worker\/#\ntopic write piphi\/worker\/set/);
  assert.match(renderIdentityAcl(parsed), /topic deny readwrite \$SYS\/#/);
});

test("identity policy rejects duplicate users, broad topics, and missing health identity", () => {
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "same", namespace: "_health", password_secret_file: "/run/secrets/a", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: true },
    { username: "same", password_secret_file: "/run/secrets/b", read: ["piphi/b/#"], write: ["piphi/b/#"], health: false },
  ]), config), /Duplicate principal/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "health", namespace: "_health", password_secret_file: "/run/secrets/health", read: ["#"], write: ["piphi/_health/#"], health: true },
  ]), config), /must stay beneath/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "worker", password_secret_file: "/run/secrets/worker", read: ["piphi/worker/#"], write: ["piphi/worker/#"], health: false },
  ]), config), /exactly one health principal/);
});

test("identity policy binds every principal to exactly one isolated namespace", () => {
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "worker", namespace: "worker", password_secret_file: "/run/secrets/worker", read: ["piphi/other/#"], write: ["piphi/worker/#"], health: false },
    { username: "health", namespace: "_health", password_secret_file: "/run/secrets/health", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: true },
  ]), config), /must stay beneath piphi\/worker/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "worker", namespace: "_health", password_secret_file: "/run/secrets/worker", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: false },
    { username: "health", namespace: "health", password_secret_file: "/run/secrets/health", read: ["piphi/health/#"], write: ["piphi/health/#"], health: true },
  ]), config), /Only the health principal/);
  assert.throws(() => parseIdentityPolicy(policy([
    { username: "worker", namespace: "worker", password_secret_file: "/run/secrets/../outside", read: ["piphi/worker/#"], write: ["piphi/worker/#"], health: false },
    { username: "health", namespace: "_health", password_secret_file: "/run/secrets/health", read: ["piphi/_health/#"], write: ["piphi/_health/#"], health: true },
  ]), config), /absolute secret path/);
});
