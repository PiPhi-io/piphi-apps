import assert from "node:assert/strict";
import test from "node:test";
import { buildConfigPayload, buildRuntimeHeaders } from "piphi-runtime-testkit-node";

import { createApp } from "../src/app.js";
import { setDriverSessionFactory } from "../src/state.js";
import { createMockDriverFactory } from "./helpers/mock-driver.js";

test("snapshot exposes bounded node metadata without controller secrets", async (t) => {
  setDriverSessionFactory(createMockDriverFactory());
  const app = createApp();
  t.after?.(() => app.close());

  const configured = await app.inject({
    method: "POST",
    url: "/config",
    headers: buildRuntimeHeaders(),
    payload: buildConfigPayload({
      id: "controller-1",
      controller_path: "/dev/serial/by-id/mock-controller",
    }),
  });
  assert.equal(configured.statusCode, 200);

  const response = await app.inject({ method: "GET", url: "/v1/zwave/snapshot" });
  assert.equal(response.statusCode, 200);
  const snapshot = JSON.parse(response.body);
  assert.equal(snapshot.schema_version, "piphi.zwave.snapshot.v1");
  assert.equal(snapshot.config_id, "controller-1");
  assert.equal(snapshot.nodes[0].node_id, 2);
  assert.equal(snapshot.nodes[0].values[0].metadata.writeable, true);
  assert.ok(snapshot.stream_id);
  assert.doesNotMatch(response.body, /network.?key|full.?dsk|raw.?frame|nvm/i);
});

test("production Z-Wave API requires the sidecar bearer token", async (t) => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousToken = process.env.PIPHI_ZWAVE_SIDECAR_TOKEN;
  process.env.NODE_ENV = "production";
  process.env.PIPHI_ZWAVE_SIDECAR_TOKEN = "sidecar-test-token-with-sufficient-entropy";
  t.after?.(() => {
    if (previousNodeEnv == null) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
    if (previousToken == null) delete process.env.PIPHI_ZWAVE_SIDECAR_TOKEN;
    else process.env.PIPHI_ZWAVE_SIDECAR_TOKEN = previousToken;
  });

  const app = createApp();
  t.after?.(() => app.close());
  const denied = await app.inject({ method: "GET", url: "/v1/zwave/events" });
  assert.equal(denied.statusCode, 401);
  const allowed = await app.inject({
    method: "GET",
    url: "/v1/zwave/events",
    headers: { authorization: "Bearer sidecar-test-token-with-sufficient-entropy" },
  });
  assert.equal(allowed.statusCode, 200);
});
