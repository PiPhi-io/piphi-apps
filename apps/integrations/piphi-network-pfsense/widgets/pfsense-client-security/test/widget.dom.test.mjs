import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const manifest = JSON.parse(await readFile(new URL("../widget.manifest.json", import.meta.url)));
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function mount(host, locale = "en", direction = "ltr") {
  const dom = new JSDOM('<div id="piphi-widget-root"></div>', { pretendToBeVisual: true });
  globalThis.window = dom.window; globalThis.document = dom.window.document;
  globalThis.requestAnimationFrame = (callback) => setTimeout(callback, 0);
  globalThis.cancelAnimationFrame = (handle) => clearTimeout(handle);
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  dom.window.PiPhiWidgetHost = {
    getContext: async () => ({ localization: { locale, direction }, bindings: [] }), getSettings: async () => ({}),
    translate: async (key) => manifest.translations[locale]?.[key] ?? key, ready: async () => undefined, setHeight: async () => undefined,
    ...host,
  };
  await import(`../src/widget.js?dom=${Date.now()}-${Math.random()}`);
  return dom;
}

test("security widget recovers an initial read and subscription failure through its DOM Retry", async () => {
  let reads = 0; let subscriptions = 0;
  const dom = await mount({
    getCapabilityState: async () => { if (++reads === 1) throw new Error("offline"); return { states: [{ capability_id: "clients_online", value: 4 }] }; },
    subscribeState: async () => { if (++subscriptions === 1) throw new Error("stream down"); return () => undefined; },
  });
  const button = dom.window.document.querySelector("[data-retry]");
  assert.equal(button.hidden, false);
  button.click(); await tick(); await tick();
  assert.equal(button.hidden, false);
  assert.equal(subscriptions, 1);
  button.click(); await tick(); await tick();
  assert.equal(reads, 3);
  assert.equal(subscriptions, 2);
  assert.equal(button.hidden, true);
  assert.equal(dom.window.document.querySelector("main").dataset.state, "live");
  assert.equal(dom.window.document.activeElement, dom.window.document.querySelector("h2"));
});

test("security widget renders localized Arabic RTL failure and a named 44px Retry contract", async () => {
  const dom = await mount({ getCapabilityState: async () => { throw new Error("offline"); }, subscribeState: async () => () => undefined }, "ar", "rtl");
  const main = dom.window.document.querySelector("main"); const button = dom.window.document.querySelector("[data-retry]");
  assert.equal(main.dir, "rtl");
  assert.equal(dom.window.document.querySelector('[role="status"]').textContent, manifest.translations.ar["status.error"]);
  assert.equal(button.textContent, manifest.translations.ar["action.retry"]);
  assert.match(dom.window.document.querySelector("style").textContent, /min-height:44px/);
});

test("security widget exposes Retry on stream close and restores one subscription", async () => {
  let emit;
  let subscriptions = 0;
  let stops = 0;
  const dom = await mount({
    getCapabilityState: async () => ({ states: [{ capability_id: "clients_online", value: 4 }] }),
    subscribeState: async (_options, callback) => {
      subscriptions += 1;
      emit = callback;
      return () => { stops += 1; };
    },
  });
  const main = dom.window.document.querySelector("main");
  const button = dom.window.document.querySelector("[data-retry]");

  emit({ status: "closed" });
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
