import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const cli = resolve(root, "node_modules/piphi-network-widget-sdk/bin/piphi-widget.mjs");
for (const slug of ["plex-server-overview", "recently-added", "continue-watching", "library-search"]) {
  const cwd = resolve(root, "widgets", slug);
  execFileSync(process.execPath, [cli, "conformance"], { cwd, stdio: "inherit" });
  execFileSync(process.execPath, ["--test", "test/widget.test.mjs"], { cwd, stdio: "inherit" });
}
