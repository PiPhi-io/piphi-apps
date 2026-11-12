import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { buildConfigPayload, buildRuntimeHeaders } from "piphi-runtime-testkit-node";

import { createApp } from "../src/app.js";

type FixtureCase = {
  id: string;
  method: "GET" | "POST";
  path: string;
  status: number;
  body?: Record<string, unknown>;
  required_keys?: string[];
  required_any_keys?: string[][];
};

const fixtures = JSON.parse(fs.readFileSync("tests/fixtures/contract-conformance.json", "utf8")) as {
  cases: FixtureCase[];
};

test("runtime conforms to shared PiPhi contract fixtures", async (t) => {
  const app = createApp();
  t.after?.(() => app.close());

  for (const fixture of fixtures.cases) {
    const payload = fixture.id === "config"
      ? buildConfigPayload(fixture.body ?? {})
      : fixture.body;
    const response = await app.inject({
      method: fixture.method,
      url: fixture.path,
      payload,
      headers: fixture.id === "config" ? buildRuntimeHeaders() : undefined,
    });
    assert.equal(response.statusCode, fixture.status, fixture.id);
    const body = JSON.parse(response.body);
    assertRequiredKeys(body, fixture.required_keys ?? [], fixture.id);
    assertRequiredAnyKeys(body, fixture.required_any_keys ?? [], fixture.id);
  }
});

function assertRequiredKeys(body: Record<string, unknown>, keys: string[], fixtureId: string): void {
  for (const key of keys) {
    assert.ok(key in body, `${fixtureId} missing ${key}`);
  }
}

function assertRequiredAnyKeys(body: Record<string, unknown>, groups: string[][], fixtureId: string): void {
  for (const group of groups) {
    assert.ok(group.some((key) => key in body), `${fixtureId} missing one of ${group.join(", ")}`);
  }
}
