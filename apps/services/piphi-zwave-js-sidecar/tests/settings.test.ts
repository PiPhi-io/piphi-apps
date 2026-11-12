import assert from "node:assert/strict";
import test from "node:test";

import { runtimePort } from "../src/settings.js";

test("Core-assigned PORT controls the managed API listener", () => {
  const previous = process.env.PORT;
  try {
    process.env.PORT = "43127";
    assert.equal(runtimePort(), 43127);
    process.env.PORT = "invalid";
    assert.throws(() => runtimePort(), /PORT/);
  } finally {
    if (previous === undefined) delete process.env.PORT;
    else process.env.PORT = previous;
  }
});
