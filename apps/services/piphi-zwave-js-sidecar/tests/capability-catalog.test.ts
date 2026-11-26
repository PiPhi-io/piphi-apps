import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createApp } from "../src/app.js";
import { setDriverSessionFactory } from "../src/state.js";
import { createMockDriverFactory } from "./helpers/mock-driver.js";

const catalog = JSON.parse(readFileSync(new URL("../capability-catalog.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
const roles = ["state", "events", "conditions", "actions"] as const;

function byStatus(status: string, role: (typeof roles)[number]): Set<string> {
  return new Set(catalog.groups.filter((group: { status: string }) => group.status === status).flatMap((group: Record<string, string[]>) => group[role]));
}

test("capability catalog is reviewable and duplicate free", () => {
  assert.equal(catalog.catalog_version, "1.0");
  assert.equal(catalog.integration_id, manifest.id);
  assert.ok(catalog.coverage_mode);
  for (const group of catalog.groups) {
    assert.ok(group.scope.length && group.source_refs.length && group.reason);
    assert.ok(group.source_refs.every((source: string) => source in catalog.sources));
    for (const role of roles) assert.equal(group[role].length, new Set(group[role]).size);
  }
  for (const role of roles) {
    const items = catalog.groups.flatMap((group: Record<string, string[]>) => group[role]);
    assert.equal(items.length, new Set(items).size, `duplicate ${role} catalog entries`);
  }
});

test("only implemented capabilities are advertised", () => {
  const implemented = new Set([...byStatus("implemented", "state"), ...byStatus("implemented", "actions")]);
  const actions = byStatus("implemented", "actions");
  assert.deepEqual(new Set(Object.keys(manifest.capabilities)), implemented);
  assert.deepEqual(new Set(Object.keys(manifest.commands)), actions);
  assert.deepEqual(manifest.entities, []);
});

test("sidecar does not fabricate PiPhi entities", () => {
  assert.deepEqual(manifest.entities, []);
  assert.equal(byStatus("implemented", "conditions").size, 0);
});

test("runtime entities remain empty after controller configuration", async (t) => {
  setDriverSessionFactory(createMockDriverFactory());
  const app = createApp();
  t.after(() => app.close());
  const configured = await app.inject({
    method: "POST",
    url: "/config",
    payload: { id: "entityless-controller", controller_path: "/dev/serial/by-id/fake" },
  });
  assert.equal(configured.statusCode, 200);
  const response = await app.inject({ method: "GET", url: "/entities" });
  const body = response.json();
  assert.deepEqual(body.entities, []);
  assert.equal("set_value" in body.commands, false);
});

for (const command of ["restart_worker", "execute_arbitrary_server_command", "factory_reset_controller"]) {
  test(`unimplemented command ${command} fails closed`, async (t) => {
    const app = createApp();
    t.after(() => app.close());
    const response = await app.inject({method: "POST", url: "/command", payload: {contract_version: "automation.runtime.command.v1", command, target: {device_id: "zwave-js-service", config_id: "zwave-js-service"}, params: {}}});
    assert.equal(response.statusCode, 400);
    assert.equal(JSON.parse(response.body).reason, `Unsupported command: ${command}`);
  });
}
