import assert from "node:assert/strict";
import test from "node:test";

import { loadSettings } from "../src/settings.js";

test("Core-assigned PORT controls the managed API listener", () => {
  assert.equal(loadSettings({ PORT: "43127", MATTER_API_PORT: "8711" }).apiPort, 43127);
  assert.throws(() => loadSettings({ PORT: "invalid" }), /PORT/);
});

test("the Matter API cannot be rebound away from loopback", () => {
  assert.throws(() => loadSettings({ MATTER_API_HOST: "0.0.0.0" }), /loopback-only/);
  assert.equal(loadSettings({ MATTER_API_HOST: "::1" }).apiHost, "::1");
});
