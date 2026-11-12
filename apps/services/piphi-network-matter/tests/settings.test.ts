import assert from "node:assert/strict";
import test from "node:test";

import { loadSettings } from "../src/settings.js";

test("Core-assigned PORT controls the managed API listener", () => {
  assert.equal(loadSettings({ PORT: "43127", MATTER_API_PORT: "8711" }).apiPort, 43127);
  assert.throws(() => loadSettings({ PORT: "invalid" }), /PORT/);
});
