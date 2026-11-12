import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createApp } from "../src/app.js";

const catalog = JSON.parse(readFileSync(new URL("../capability-catalog.json", import.meta.url), "utf8"));
const manifest = JSON.parse(readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
const example = JSON.parse(readFileSync(new URL("../examples/entity-response.json", import.meta.url), "utf8"));
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
  const entityCapabilities = new Set(manifest.entities.flatMap((entity: { capabilities: string[] }) => entity.capabilities));
  const entityCommands = new Set(manifest.entities.flatMap((entity: { available_commands: { id: string }[] }) => entity.available_commands.map((command) => command.id)));
  assert.deepEqual(new Set(Object.keys(manifest.capabilities)), implemented);
  assert.deepEqual(new Set(Object.keys(manifest.commands)), actions);
  assert.deepEqual(entityCapabilities, implemented);
  assert.deepEqual(entityCommands, actions);
  assert.deepEqual(new Set(Object.keys(example.capabilities)), implemented);
  assert.deepEqual(new Set(Object.keys(example.commands)), actions);
});

test("sidecar has only a driver service entity", () => {
  assert.equal(manifest.entities.length, 1);
  assert.equal(manifest.entities[0].id, "zwave-js-service");
  assert.equal(manifest.entities[0].entity_type, "service");
  assert.equal(byStatus("implemented", "conditions").size, 0);
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
