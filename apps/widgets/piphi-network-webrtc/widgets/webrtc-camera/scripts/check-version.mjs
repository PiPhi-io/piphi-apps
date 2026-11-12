import assert from "node:assert/strict";
import packageJson from "../package.json" with { type: "json" };
import manifest from "../widget.manifest.json" with { type: "json" };

assert.equal(packageJson.version, manifest.version, "package.json and widget.manifest.json versions must match");
if (process.env.GITHUB_REF_TYPE === "tag") {
  assert.equal(process.env.GITHUB_REF_NAME, `v${packageJson.version}`, "Release tag must match the widget version");
}
console.log(`Version ${packageJson.version} is synchronized.`);
