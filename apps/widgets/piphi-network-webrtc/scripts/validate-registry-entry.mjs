import assert from "node:assert/strict";
import entry from "../registry/widget-entry.json" with { type: "json" };
import manifest from "../widgets/webrtc-camera/widget.manifest.json" with { type: "json" };
import packageJson from "../widgets/webrtc-camera/package.json" with { type: "json" };

assert.equal(entry.type, "widget");
assert.equal(entry.id, manifest.id);
assert.equal(entry.name, manifest.name);
assert.equal(entry.version, manifest.version);
assert.equal(packageJson.version, manifest.version);
assert.equal(entry.manifest_path, "widgets/webrtc-camera/widget.manifest.json");
assert.equal(entry.marketplace.metadata_version, 2);
assert.deepEqual(entry.marketplace, manifest.marketplace, "Registry marketplace metadata must match the widget manifest");
assert.equal(entry.marketplace.governance.publication_status, "draft");
assert.equal(entry.marketplace.governance.rollout_percent, 0);
assert.match(entry.artifact.integrity, /^sha256:[a-f0-9]{64}$/, "Packed widget must declare immutable archive integrity");
assert.equal(entry.artifact.release_asset, manifest.artifact.release_asset, "Release asset names must match");
assert.deepEqual(entry.runtime_requirements.sort(), ["browser_webrtc", "camera_broker"]);
console.log(`Draft widget registry entry ${entry.id}@${entry.version} is synchronized.`);
