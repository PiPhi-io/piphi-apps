import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { selfTestHardwareReportValidator } from "./validate-hardware-report.mjs";

const readJson = async (path) => JSON.parse(await readFile(path, "utf8"));
const [pkg, manifest, behaviors, catalog, hardware] = await Promise.all([
  readJson("package.json"),
  readJson("src/manifest.json"),
  readJson("src/behaviors.json"),
  readJson("src/capability-catalog.json"),
  readJson("docs/hardware-qualification.json"),
]);

assert.equal(manifest.id, "piphi.service.matter-sidecar");
assert.equal(manifest.kind, "platform_service");
assert.equal(manifest.version, pkg.version);
assert.equal(manifest.runtime.linux.container.image, `ghcr.io/piphi-io/matter-sidecar:${pkg.version}`);
assert.equal(manifest.runtime.linux.container.privileged, false);
assert.equal(pkg.dependencies["@stoprocent/noble"], "2.8.0", "BLE scanner must be a production dependency");
assert.equal(hardware.schema_version, 1);
assert.equal(hardware.release, pkg.version);
assert.ok(Array.isArray(hardware.publications) && hardware.publications.length > 0, "published releases are required");
assert.equal(new Set(hardware.publications.map((publication) => publication.release)).size, hardware.publications.length);
for (const publication of hardware.publications) {
  assert.match(publication.index_digest ?? "", /^sha256:[a-f0-9]{64}$/, "published image index digest is required");
  assert.ok(publication.release, "published release version is required");
  assert.ok(["qualified", "failed", "pending_hardware"].includes(publication.production_status), "published release production status is required");
  if (publication.production_status === "failed") assert.ok(publication.production_failure, "failed publication requires a reason");
}
const currentPublication = hardware.publications.find((publication) => publication.release === hardware.release);
if (currentPublication) assert.equal(currentPublication.image, manifest.runtime.linux.container.image);
assert.deepEqual(hardware.policy.supported_transports.sort(), ["ethernet", "wifi_on_network"]);
assert.deepEqual(hardware.policy.experimental_transports.sort(), ["ble", "thread"]);
const profileIds = hardware.profiles.map((profile) => profile.id);
assert.equal(new Set(profileIds).size, profileIds.length, "hardware qualification profile IDs must be unique");
assert.deepEqual([...profileIds].sort(), [...hardware.policy.required_profiles].sort());
for (const profile of hardware.profiles) {
  assert.ok(["pending_hardware", "qualified", "failed", "blocked"].includes(profile.status));
  assert.ok(["pending_hardware", "pending_published_digest", "qualified", "failed", "blocked"].includes(profile.production_status));
  assert.ok(hardware.policy.supported_transports.includes(profile.transport));
  if (profile.status === "qualified") {
    assert.ok(profile.evidence.length > 0, `qualified hardware profile ${profile.id} requires evidence`);
    const covered = new Set(profile.evidence.flatMap((entry) => entry.steps ?? []));
    for (const step of hardware.policy.qualification_steps) {
      assert.ok(covered.has(step), `qualified hardware profile ${profile.id} is missing ${step}`);
    }
  } else {
    assert.ok(profile.blocker, `unqualified hardware profile ${profile.id} requires a blocker`);
  }
  if (profile.production_status === "qualified") {
    const publication = hardware.publications.find((candidate) => candidate.release === profile.production_release);
    assert.ok(publication, `production release ${profile.production_release} is not recorded`);
    assert.ok(profile.evidence.some((entry) => (
      entry.evidence_level === "published"
      && entry.image_digest === publication.index_digest
      && /^sha256:[a-f0-9]{64}$/.test(entry.platform_manifest_digest ?? "")
    )), `production-qualified profile ${profile.id} requires exact published-digest evidence`);
  } else {
    assert.ok(profile.production_blocker, `production-unqualified profile ${profile.id} requires a blocker`);
  }
}
selfTestHardwareReportValidator(hardware);

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
