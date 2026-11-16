import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("quality ledger remains unrated and all completed evidence exists", async () => {
  const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
  const ledger = JSON.parse(await readFile(resolve(packageRoot, "quality-scale.yaml"), "utf8")) as {
    target_tier: string;
    rules: Record<string, { status: string; evidence?: string[]; comment?: string }>;
  };
  const manifest = JSON.parse(await readFile(resolve(packageRoot, "manifest.json"), "utf8")) as {
    marketplace: { quality_tier: string };
  };

  assert.equal(ledger.target_tier, "unrated");
  assert.equal(manifest.marketplace.quality_tier, "unrated");
  for (const [rule, entry] of Object.entries(ledger.rules)) {
    if (entry.status === "done") {
      assert.ok(entry.evidence?.length, `${rule} must link evidence`);
      for (const path of entry.evidence ?? []) await access(resolve(packageRoot, path));
    } else {
      assert.ok(entry.comment, `${rule} must explain ${entry.status}`);
    }
  }
});
