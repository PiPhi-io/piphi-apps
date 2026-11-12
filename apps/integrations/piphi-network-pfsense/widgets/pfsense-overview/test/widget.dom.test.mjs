import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const manifest = JSON.parse(await readFile(new URL("../widget.manifest.json", import.meta.url)));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function mount(host, locale = "en", direction = "ltr") {
  const dom = new JSDOM('<div id="piphi-widget-root"></div>', { pretendToBeVisual: true });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
  globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  dom.window.PiPhiWidgetHost = {
    getContext: async () => ({ localization: { locale, direction }, bindings: [] }),
    getSettings: async () => ({}),
    translate: async (key) => manifest.translations[locale]?.[key] ?? key,
    ready: async () => undefined,
    setHeight: async () => undefined,
    ...host,
  };
  await import(`../src/widget.js?dom=${Date.now()}-${Math.random()}`);
  return dom;
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

test("Arabic RTL error retries one read, restores subscription, busy state, and focus", async () => {
  const retryRead = deferred();
  let reads = 0;
  let subscriptions = 0;
  const dom = await mount({
    getCapabilityState: () => ++reads === 1 ? Promise.reject(new Error("offline")) : retryRead.promise,
    subscribeState: async () => { subscriptions += 1; return () => undefined; },
  }, "ar", "rtl");
  const main = dom.window.document.querySelector("main");
  const button = dom.window.document.querySelector("[data-retry]");
  assert.equal(main.dir, "rtl");
  assert.equal(button.hidden, false);
  assert.equal(button.textContent, manifest.translations.ar["action.retry"]);
  button.click();
  assert.equal(main.getAttribute("aria-busy"), "true");
  assert.equal(button.disabled, true);
  button.click();
  retryRead.resolve({ states: [{ capability_id: "connected", value: true }, { capability_id: "cpu_usage_percent", value: 28 }] });
  await tick(); await tick();
  assert.equal(reads, 2);
  assert.equal(subscriptions, 1);
  assert.equal(button.hidden, true);
  assert.equal(main.hasAttribute("aria-busy"), false);
  assert.equal(dom.window.document.activeElement, dom.window.document.querySelector("h2"));
});

test("a successful offline snapshot keeps status and Retry visible", async () => {
  const dom = await mount({
    getCapabilityState: async () => ({ states: [{ capability_id: "connected", value: false }, { capability_id: "cpu_usage_percent", value: 28 }] }),
    subscribeState: async () => () => undefined,
  });
  const main = dom.window.document.querySelector("main");
  assert.equal(main.dataset.state, "offline");
  assert.equal(main.dataset.stale, "true");
  assert.equal(dom.window.document.querySelector("[data-retry]").hidden, false);
  assert.equal(dom.window.document.querySelector('[role="status"]').textContent, "Router is offline");
});

test("a streamed offline snapshot cannot erase the Retry state", async () => {
  let emit;
  const dom = await mount({
    getCapabilityState: async () => ({ states: [{ capability_id: "connected", value: true }] }),
    subscribeState: async (_options, callback) => { emit = callback; return () => undefined; },
  });
  emit({ kind: "snapshot", data: { states: [{ capability_id: "connected", value: false }] } });
  await tick();
  assert.equal(dom.window.document.querySelector("main").dataset.state, "offline");
  assert.equal(dom.window.document.querySelector("[data-retry]").hidden, false);
  emit({ kind: "reconnecting" });
  await tick();
  assert.equal(dom.window.document.querySelector("main").dataset.state, "offline");
  assert.equal(dom.window.document.querySelector("[data-retry]").hidden, false);
});

test("a failed subscription is restored by Retry before the card becomes live", async () => {
  let subscriptions = 0;
  const dom = await mount({
    getCapabilityState: async () => ({ states: [{ capability_id: "connected", value: true }] }),
    subscribeState: async () => { if (++subscriptions === 1) throw new Error("stream unavailable"); return () => undefined; },
  });
  const button = dom.window.document.querySelector("[data-retry]");
  assert.equal(button.hidden, false);
  button.click();
  await tick(); await tick();
  assert.equal(subscriptions, 2);
  assert.equal(button.hidden, true);
  assert.equal(dom.window.document.querySelector("main").dataset.state, "live");
});

test("a closed live stream exposes Retry and restores exactly one subscription", async () => {
  let emit;
  let subscriptions = 0;
  let stops = 0;
  const dom = await mount({
    getCapabilityState: async () => ({
      states: [
        { capability_id: "connected", value: true },
        { capability_id: "cpu_usage_percent", value: 28 },
      ],
    }),
    subscribeState: async (_options, callback) => {
      subscriptions += 1;
      emit = callback;
      return () => { stops += 1; };
    },
  });
  const main = dom.window.document.querySelector("main");
  const button = dom.window.document.querySelector("[data-retry]");

  emit({ kind: "closed" });
  await tick();
  assert.equal(main.dataset.state, "error");
  assert.equal(main.dataset.stale, "true");
  assert.equal(button.hidden, false);
  assert.equal(stops, 1);

  button.click();
  button.click();
  await tick(); await tick();
  assert.equal(subscriptions, 2);
  assert.equal(button.hidden, true);
  assert.equal(main.dataset.state, "live");
  assert.equal(dom.window.document.activeElement, dom.window.document.querySelector("h2"));
});
