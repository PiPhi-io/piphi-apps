import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRecoverySession, resolveConnectionAttention, resolveStatus, statusText } from "../src/state.js";

const manifest = JSON.parse(await readFile(new URL("../widget.manifest.json", import.meta.url)));

test("widget declares a sandboxed, read-only runtime contract", () => {
  assert.equal(manifest.id, "io.piphi.pfsense.overview");
  assert.deepEqual(manifest.binding_modes, ["read"]);
  assert.deepEqual(manifest.security.permissions, []);
  assert.ok(manifest.capability_requirements.includes("connected"));
});

test("widget uses a compact, theme-aware host surface", async () => {
  const source = await readFile(new URL("../src/widget.js", import.meta.url), "utf8");
  assert.match(source, /background:transparent/);
  assert.match(source, /data\.states/);
  assert.match(source, /Internet & router/);
  assert.match(source, /Services needing attention/);
  assert.doesNotMatch(source, /Connections working|Secure connections/);
  assert.doesNotMatch(source, /Gateways up|Services down|Live firewall data/);
  assert.equal(manifest.layout.transparent, true);
  assert.equal(manifest.layout.default_height, 160);
  assert.match(source, /host\.ready\(\{ height: Math\.ceil\(card\.scrollHeight\) \}\)/);
  assert.match(source, /host\.setHeight\(Math\.ceil\(card\.scrollHeight\)\)/);
  assert.doesNotMatch(source, /main\{min-height:/);
  assert.match(source, /grid-auto-rows:minmax\(52px,auto\)/);
  assert.match(source, /--piphi-widget-font-size-label/);
  assert.match(source, /--piphi-widget-font-size-value/);
  assert.match(source, /font-size:var\(--pfsense-label-size\)/);
  assert.match(source, /font-size:var\(--pfsense-value-size\)/);
  assert.doesNotMatch(source, /Updated just now/);
  assert.match(source, /\.status-row\[hidden\]\{display:none\}/);
  assert.match(source, /ResizeObserver/);
  assert.match(source, /@media\(max-width:360px\)/);
  assert.match(source, /@media\(max-width:180px\)/);
  assert.doesNotMatch(source, /@media\(max-width:240px\).*grid-template-columns:1fr/);
  assert.match(source, /\.health\[hidden\]\{display:none\}/);
  assert.doesNotMatch(source, /connected \? "Online"/);
  assert.match(source, /@media\(forced-colors:active\)/);
  assert.match(source, /min-height:44px/);
  assert.match(source, /data-stale/);
  assert.match(source, /createRecoverySession/);
  assert.ok(source.lastIndexOf("retryButton.disabled = false") < source.lastIndexOf("retryButton.focus()"));
  assert.doesNotMatch(source, /\.card\{[^}]*border:1px/);
});

test("healthy connection stays quiet while disconnect and recovery remain explicit", () => {
  assert.deepEqual(resolveConnectionAttention(true), { connected: true, hidden: true, label: "" });
  assert.deepEqual(resolveConnectionAttention(false), { connected: false, hidden: false, label: "Offline" });
  assert.deepEqual(resolveConnectionAttention("online"), { connected: true, hidden: true, label: "" });
});

test("transient errors recover to a quiet live state", () => {
  assert.equal(statusText({ kind: "error" }), "Unable to update router status");
  assert.equal(statusText({ kind: "reconnecting" }), "Updating router status…");
  assert.equal(statusText({ kind: "snapshot" }), "");
});

test("failed refresh exposes retry, deduplicates clicks, and clears only after recovery", async () => {
  const transitions = [];
  let attempts = 0;
  let releaseFailure;
  const firstFailure = new Promise((_, reject) => { releaseFailure = () => reject(new Error("offline")); });
  let subscriptions = 0;
  const session = createRecoverySession({
    read: () => (++attempts === 1 ? firstFailure : Promise.resolve({ states: [{ capability_id: "connected", value: true }] })),
    subscribe: async () => { subscriptions += 1; return () => undefined; },
    onStart: () => transitions.push("busy"),
    onRecovered: () => transitions.push("live"),
    onError: () => transitions.push("error"),
    onSettled: () => transitions.push("idle"),
  });
  const first = session.recover();
  const duplicate = session.recover();
  assert.equal(first, duplicate);
  assert.equal(attempts, 0);
  releaseFailure();
  await first;
  assert.deepEqual(transitions, ["busy", "error", "idle"]);
  await session.recover({ restoreFocus: true });
  assert.equal(attempts, 2);
  assert.equal(subscriptions, 1);
  assert.deepEqual(transitions, ["busy", "error", "idle", "busy", "live", "idle"]);
});

test("a failed subscription is restored exactly once on retry", async () => {
  let subscriptions = 0;
  const phases = [];
  const session = createRecoverySession({
    read: async () => ({ states: [{ capability_id: "connected", value: true }] }),
    subscribe: async () => { if (++subscriptions === 1) throw new Error("stream down"); return () => undefined; },
    onRecovered: () => phases.push("live"), onError: () => phases.push("error"),
  });
  await session.recover();
  assert.equal(session.hasSubscription(), false);
  await Promise.all([session.recover(), session.recover()]);
  assert.equal(subscriptions, 2);
  assert.equal(session.hasSubscription(), true);
  assert.deepEqual(phases, ["error", "live"]);
});

test("status model marks retained readings stale and offers a retry", () => {
  const copy = { updating: "Updating", stale: "Last known", offline: "Offline", error: "Error", waiting: "Waiting" };
  assert.deepEqual(resolveStatus({ kind: "error" }, copy, true), {
    phase: "error", message: "Error", stale: true, retry: true,
  });
  assert.deepEqual(resolveStatus({ kind: "snapshot" }, copy, true), {
    phase: "live", message: "", stale: false, retry: false,
  });
});

test("every supported locale provides complete visible and recovery copy", () => {
  const required = Object.keys(manifest.translations.en);
  for (const locale of ["en", "es", "ar"]) {
    assert.deepEqual(Object.keys(manifest.translations[locale]).sort(), required.sort());
    for (const key of required) assert.ok(manifest.translations[locale][key].trim());
  }
});

test("light and dark previews match the quiet divider-based runtime", async () => {
  const previews = await Promise.all(["light", "dark"].map((theme) =>
    readFile(new URL(`../previews/${theme}.svg`, import.meta.url), "utf8")
  ));
  for (const preview of previews) {
    assert.doesNotMatch(preview, />Online</);
    assert.doesNotMatch(preview, /<rect x="12" y="36"/);
    assert.doesNotMatch(preview, /font-size="10\.5"/);
    assert.match(preview, /font-size="12"/);
    assert.match(preview, /<path d="M12 36H402"/);
  }
});
