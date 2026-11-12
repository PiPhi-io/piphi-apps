import assert from "node:assert/strict";
import test from "node:test";

import { createApp } from "../src/app.js";
import { commands } from "../src/contract.js";

test("runtime implements the advertised contract routes", async (t) => {
  const app = createApp();
  t.after?.(() => app.close());

  const health = await app.inject({ method: "GET", url: "/health" });
  assert.equal(health.statusCode, 200);
  assert.equal(JSON.parse(health.body).ok, true);

  const diagnostics = await app.inject({ method: "GET", url: "/diagnostics" });
  assert.equal(diagnostics.statusCode, 200);
  assert.deepEqual(JSON.parse(diagnostics.body).diagnostics.contract.required, [
    "health",
    "entities",
    "command",
    "config",
    "ui_config",
  ]);

  for (const url of ["/ui-config", "/entities", "/state", "/contract", "/events"]) {
    const response = await app.inject({ method: "GET", url });
    assert.equal(response.statusCode, 200, url);
  }

  const missingCommand = await app.inject({
    method: "POST",
    url: "/command",
    payload: { command: "does_not_exist" },
  });
  assert.equal(missingCommand.statusCode, 400);

  assert.ok("refresh" in commands);
});
