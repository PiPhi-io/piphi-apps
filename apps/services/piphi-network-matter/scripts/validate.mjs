import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const readJson = async (path) => JSON.parse(await readFile(path, "utf8"));
const [pkg, manifest, behaviors, catalog] = await Promise.all([
  readJson("package.json"),
  readJson("src/manifest.json"),
  readJson("src/behaviors.json"),
  readJson("src/capability-catalog.json"),
]);

assert.equal(manifest.id, "piphi.service.matter-sidecar");
assert.equal(manifest.kind, "platform_service");
assert.equal(manifest.version, pkg.version);
assert.equal(manifest.runtime.linux.container.image, `piphinetwork/matter-sidecar:${pkg.version}`);
assert.equal(manifest.runtime.linux.container.privileged, false);

const rows = catalog.capabilities;
const ids = rows.map((row) => row.id);
assert.equal(new Set(ids).size, ids.length, "capability catalog IDs must be unique");
const implemented = new Set(rows.filter((row) => row.status === "implemented").map((row) => row.id));
const advertised = new Set(behaviors.devices.flatMap((device) => device.capabilities));
const required = new Set(behaviors.devices.flatMap((device) => [
  ...device.capabilities,
  ...device.conditions.flatMap((condition) => condition.capabilityRequirements ?? []),
  ...device.actions.flatMap((action) => action.capabilityRequirements ?? []),
]));
for (const mapping of behaviors.telemetry.capabilityMappings) required.add(mapping.nativeMetric);
for (const capability of required) {
  assert.ok(implemented.has(capability), `advertised capability ${capability} is not implemented`);
}
for (const row of rows.filter((item) => item.status !== "implemented")) {
  assert.ok(!advertised.has(row.id), `${row.status} capability ${row.id} must not be advertised`);
}
const implementedActions = new Set(rows.filter((row) => row.status === "implemented" && row.kind === "action").map((row) => row.id));
const behaviorActions = new Set(behaviors.devices.flatMap((device) => device.actions.map((action) => action.id)));
assert.deepEqual([...behaviorActions].sort(), [...implementedActions].sort(), "behavior actions and implemented catalog actions must agree");

console.log(`Validated Matter sidecar ${pkg.version}: ${implemented.size} implemented capabilities.`);
