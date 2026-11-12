import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";

import { formatReading, mountAwairWidget, scoreBand, statesFromEvent } from "../assets/awair-widget.mjs";

const bootstrap = {
  protocol: "piphi.widget.host",
  version: "1",
  type: "piphi.widget.bootstrap",
  instanceId: "awair-test",
  settings: {},
  binding: null,
  bindings: [
    { id: "score", label: "Score", role: "primary", binding: {} },
    { id: "co2", label: "CO2", role: "secondary", binding: {} },
  ],
  layout: { defaultHeight: 180, minHeight: 120, maxHeight: 1200 },
};

function harness() {
  const dom = new JSDOM('<div id="piphi-widget-root"></div>');
  const callbacks = new Map();
  const interactions = [];
  const host = {
    subscribe(callback) { callback(bootstrap); return () => undefined; },
    async subscribeState({ slotId }, callback) { callbacks.set(slotId, callback); return async () => callbacks.delete(slotId); },
    async ready() { return { ok: true, height: 180 }; },
    async setHeight(height) { return { ok: true, height }; },
    async activateInteraction(targetId) { interactions.push(targetId); return { ok: true, action: "more-info", targetId }; },
  };
  return { dom, root: dom.window.document.getElementById("piphi-widget-root"), callbacks, interactions, host };
}

test("score and reading helpers normalize device data", () => {
  assert.deepEqual(scoreBand(93), { label: "Excellent", tone: "excellent" });
  assert.deepEqual(scoreBand(55), { label: "Needs attention", tone: "poor" });
  assert.equal(formatReading({ value: 612.25 }, "ppm"), "612.3 ppm");
  assert.deepEqual(statesFromEvent({ kind: "point", data: { value: 82 } }, "score")[0].id, "score");
});

test("widget covers loading, live, stale, error, interaction, and cleanup states", async () => {
  const { dom, root, callbacks, interactions, host } = harness();
  const cleanup = mountAwairWidget(root, host);
  assert.match(root.innerHTML, /aria-busy="true"/);
  await new Promise((resolve) => setTimeout(resolve, 0));
  callbacks.get("score")({ kind: "point", data: { value: 91, collected_at: new Date().toISOString() } });
  callbacks.get("co2")({ kind: "point", data: { value: 580, unit: "ppm" } });
  assert.match(root.textContent, /Excellent/);
  assert.match(root.textContent, /580 ppm/);
  root.querySelector('[data-target="co2"]').click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(interactions, ["co2"]);
  callbacks.get("score")({ kind: "status", status: "stale" });
  assert.match(root.textContent, /updates delayed/);
  callbacks.get("score")({ kind: "error", error: { message: "Awair is offline" } });
  assert.match(root.innerHTML, /role="alert"/);
  assert.match(root.textContent, /Awair is offline/);
  await cleanup();
  assert.equal(callbacks.size, 0);
  dom.window.close();
});
