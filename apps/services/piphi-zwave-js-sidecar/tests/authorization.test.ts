import assert from "node:assert/strict";
import test from "node:test";

import { createApp } from "../src/app.js";

test("only liveness is public when sidecar authorization is configured", async (t) => {
  const previousNodeEnv = process.env.NODE_ENV;
  const previousToken = process.env.PIPHI_ZWAVE_SIDECAR_TOKEN;
  process.env.NODE_ENV = "production";
  process.env.PIPHI_ZWAVE_SIDECAR_TOKEN = "sidecar-secret";
  const app = createApp();
  t.after(async () => {
    await app.close();
    if (previousNodeEnv === undefined) delete process.env.NODE_ENV;
    else process.env.NODE_ENV = previousNodeEnv;
    if (previousToken === undefined) delete process.env.PIPHI_ZWAVE_SIDECAR_TOKEN;
    else process.env.PIPHI_ZWAVE_SIDECAR_TOKEN = previousToken;
  });

  assert.equal((await app.inject({ method: "GET", url: "/health" })).statusCode, 200);
  const routes = [
    ["GET", "/diagnostics"], ["POST", "/discover"], ["GET", "/ui-config"],
    ["POST", "/config"], ["POST", "/config/sync"], ["POST", "/deconfigure"],
    ["POST", "/deconfigure/controller"], ["GET", "/state"], ["GET", "/contract"],
    ["GET", "/entities"], ["GET", "/events"], ["GET", "/v1/zwave/events"],
    ["GET", "/v1/zwave/snapshot"], ["POST", "/events/example"],
    ["POST", "/events/device/controller/example"], ["POST", "/telemetry/example"],
    ["POST", "/telemetry/device/controller/example"], ["POST", "/command"],
  ] as const;
  for (const [method, url] of routes) {
    const response = await app.inject({ method, url, payload: method === "POST" ? {} : undefined });
    assert.equal(response.statusCode, 401, `${method} ${url}`);
  }

  assert.equal((await app.inject({
    method: "GET",
    url: "/contract",
    headers: { authorization: "Bearer sidecar-secret" },
  })).statusCode, 200);
});
