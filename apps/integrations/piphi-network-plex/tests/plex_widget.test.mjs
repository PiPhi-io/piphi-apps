import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const flush = () => new Promise(setImmediate);

test("overview stays glance-first and renders live telemetry", async () => {
  const nodes = new Map();
  const subscriptions = new Map();
  const root = {
    innerHTML: "",
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {
        textContent: "", hidden: true, disabled: false, listeners: {},
        classList: { toggle() {} },
        addEventListener(type, listener) { this.listeners[type] = listener; },
        removeEventListener(type) { delete this.listeners[type]; },
        setAttribute(name, value) { this[name] = value; },
      });
      return nodes.get(selector);
    },
  };
  const host = {
    getSettings: async () => ({ title: "Movie night" }),
    getContext: async () => ({ props: {
      provider: "plex", machineId: "home", view: "collection", collectionId: "1",
      item: { title: "<img src=x onerror=alert(1)>" },
    } }),
    getCapabilityState: async ({ slotId }) => ({ primaryState: { value: {
      connected: true, "server-count": 2, "active-sessions": 3, "transcode-sessions": 1,
    }[slotId] } }),
    subscribeState: async ({ slotId }, callback) => {
      subscriptions.set(slotId, callback);
      return () => {};
    },
    ready: async () => {},
  };
  const bundle = await readFile(new URL("../widgets/plex-server-overview/dist/widget.js", import.meta.url), "utf8");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction("window", "document", bundle)(
    { PiPhiWidgetHost: host, addEventListener() {}, setTimeout: () => 1, clearTimeout() {} }, { querySelector: () => root },
  );
  assert.equal(nodes.get("h2").textContent, "Movie night");
  assert.ok(!root.innerHTML.includes("Saved media selection"));
  assert.ok(!root.innerHTML.includes("onerror=alert"));
  assert.equal(nodes.get(".sessions").textContent, "3");
  assert.equal(nodes.get(".issue").hidden, true);
  subscriptions.get("connected")({ kind: "point", data: { value: false } });
  assert.equal(nodes.get(".issue").hidden, false);
  assert.equal(nodes.get(".status").textContent, "Plex is offline");
  subscriptions.get("connected")({ kind: "point", data: { value: true } });
  assert.equal(nodes.get(".issue").hidden, true);
  subscriptions.get("connected")({ kind: "snapshot", status: "stale", data: { primaryState: { value: true } } });
  assert.equal(nodes.get(".status").textContent, "Plex data may be out of date");
  assert.equal(nodes.get(".retry").hidden, false);
  subscriptions.get("connected")({ kind: "point", data: { value: true } });
  subscriptions.get("active-sessions")({ kind: "snapshot", status: "reconnecting", data: { primaryState: { value: 3 } } });
  subscriptions.get("active-sessions")({ kind: "error" });
  assert.equal(nodes.get(".issue").hidden, true, "a fresh snapshot stays healthy when a preferred stream closes");
  assert.equal(nodes.get(".sessions").textContent, "3");
});

test("overview reports unavailable readings without hiding known values", async () => {
  const source = await readFile(
    new URL("../widgets/plex-server-overview/src/widget.js", import.meta.url),
    "utf8",
  );
  assert.match(source, /createRecoverySession/);
  assert.match(source, /resolveRecoveryStatus/);
  assert.match(source, /problems\.set\(slotId/);
  assert.match(source, /values\.get\("active-sessions"\) \?\? "—"/);
  assert.match(source, /source:"stream-fallback"/);
});

test("overview clears a transient read error after the user retries", async () => {
  const nodes = new Map();
  let activeSessionReads = 0;
  const root = {
    innerHTML: "",
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {
        textContent:"", hidden:true, disabled:false, listeners:{}, classList:{ toggle() {} },
        addEventListener(type, listener) { this.listeners[type] = listener; },
        removeEventListener(type) { delete this.listeners[type]; },
        setAttribute(name, value) { this[name] = value; },
      });
      return nodes.get(selector);
    },
  };
  const host = {
    getSettings: async () => ({}),
    getCapabilityState: async ({ slotId }) => {
      if (slotId === "active-sessions" && activeSessionReads++ === 0) throw new Error("temporary");
      return { primaryState:{ value:slotId === "connected" ? true : 1 } };
    },
    subscribeState: async () => () => {},
    ready: async () => {},
  };
  const bundle = await readFile(new URL("../widgets/plex-server-overview/dist/widget.js", import.meta.url), "utf8");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction("window", "document", bundle)(
    { PiPhiWidgetHost:host, addEventListener() {} },
    { querySelector:() => root },
  );
  assert.equal(nodes.get(".status").textContent, "Plex readings are unavailable");
  assert.equal(nodes.get(".issue").hidden, false);
  await nodes.get(".retry").listeners.click();
  assert.equal(nodes.get(".issue").hidden, true);
});

test("closed preferred stream preserves its snapshot and replaces the subscription in the background", async () => {
  const dom = new JSDOM("<!doctype html><div id=\"piphi-widget-root\"></div>");
  const callbacks = new Map();
  const subscribeCounts = new Map();
  let releaseActiveRead;
  let holdActiveRead = false;
  const host = {
    getSettings: async () => ({}),
    getCapabilityState: async ({ slotId }) => {
      if (slotId === "active-sessions" && holdActiveRead) {
        await new Promise((resolve) => { releaseActiveRead = resolve; });
        holdActiveRead = false;
      }
      return { primaryState: { value: slotId === "connected" ? true : 1 } };
    },
    subscribeState: async ({ slotId }, callback) => {
      callbacks.set(slotId, callback);
      subscribeCounts.set(slotId, (subscribeCounts.get(slotId) || 0) + 1);
      return () => {};
    },
    ready: async () => {},
    setHeight: async () => {},
  };
  dom.window.PiPhiWidgetHost = host;
  dom.window.setTimeout = (callback) => { queueMicrotask(callback); return 1; };
  dom.window.clearTimeout = () => {};
  const bundle = await readFile(new URL("../widgets/plex-server-overview/dist/widget.js", import.meta.url), "utf8");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction("window", "document", bundle)(dom.window, dom.window.document);

  holdActiveRead = true;
  callbacks.get("active-sessions")({ kind: "closed" });
  const retry = dom.window.document.querySelector(".retry");
  await flush();
  assert.equal(dom.window.document.querySelector(".issue").hidden, true);
  assert.equal(retry.hidden, true);
  assert.equal(subscribeCounts.get("active-sessions"), 1, "a replacement waits for the recovery read");

  releaseActiveRead();
  await flush();
  await flush();
  assert.equal(subscribeCounts.get("active-sessions"), 2, "closed stream receives one replacement subscription");
  assert.equal(dom.window.document.querySelector(".issue").hidden, true);
});

test("overview declares responsive accessible theme behavior", async () => {
  const source = await readFile(
    new URL("../widgets/plex-server-overview/src/widget.js", import.meta.url),
    "utf8",
  );
  assert.match(source, /color-scheme:light dark/);
  assert.match(source, /@container \(max-width:300px\)/);
  assert.match(source, /forced-colors:active/);
  assert.match(source, /role="status" aria-live="polite"/);
  assert.match(source, /setAttribute\("aria-label", copy\.activity\)/);
  assert.match(source, /issue\.hidden = !message/);
  assert.match(source, /min-height:44px/);
  assert.match(source, /--piphi-widget-font-size-label,12px/);
  assert.match(source, /border-inline-start/, "RTL uses logical border placement");
  assert.doesNotMatch(source, />Connected</);
  assert.doesNotMatch(source, /class="stat"[^>]*style=/);
});

test("overview localizes recovery copy and metric labels in RTL", async () => {
  const dom = new JSDOM("<!doctype html><html dir=\"rtl\"><body><div id=\"piphi-widget-root\"></div></body></html>");
  const arabic = {
    "plex.title.servers": "خوادم Plex",
    "plex.activity.label": "نشاط خادم Plex",
    "plex.metric.servers": "الخوادم",
    "plex.metric.streams": "عمليات البث",
    "plex.metric.transcodes": "التحويلات",
    "plex.status.error": "قراءات Plex غير متاحة",
    "common.retry": "إعادة المحاولة",
  };
  const host = {
    getSettings: async () => ({ title: "Plex servers" }),
    translate: async (key) => arabic[key] ?? key,
    getCapabilityState: async ({ slotId }) => {
      if (slotId === "active-sessions") throw new Error("offline");
      return { primaryState: { value: slotId === "connected" ? true : 1 } };
    },
    subscribeState: async () => () => {},
    ready: async () => {},
    setHeight: async () => {},
  };
  dom.window.PiPhiWidgetHost = host;
  const bundle = await readFile(new URL("../widgets/plex-server-overview/dist/widget.js", import.meta.url), "utf8");
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  await new AsyncFunction("window", "document", bundle)(dom.window, dom.window.document);

  assert.equal(dom.window.document.documentElement.dir, "rtl");
  assert.equal(dom.window.document.querySelector("h2").textContent, arabic["plex.title.servers"]);
  assert.equal(dom.window.document.querySelector(".stats").getAttribute("aria-label"), arabic["plex.activity.label"]);
  assert.equal(dom.window.document.querySelector(".servers-label").textContent, arabic["plex.metric.servers"]);
  assert.equal(dom.window.document.querySelector(".status").textContent, arabic["plex.status.error"]);
  assert.equal(dom.window.document.querySelector(".retry").textContent, arabic["common.retry"]);
});

test("overview selector previews and integration registration match the runtime", async () => {
  const [light, dark, integration, standalone] = await Promise.all([
    readFile(new URL("../widgets/plex-server-overview/preview-light.svg", import.meta.url), "utf8"),
    readFile(new URL("../widgets/plex-server-overview/preview-dark.svg", import.meta.url), "utf8"),
    readFile(new URL("../manifest.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../widgets/plex-server-overview/widget.manifest.json", import.meta.url), "utf8").then(JSON.parse),
  ]);
  assert.doesNotMatch(light + dark, /Connected|rx="14"/);
  assert.match(light + dark, /font-size="12"/);
  const registered = integration.ui.widget_packages.find((item) => item.id === standalone.id);
  assert.equal(registered.version, standalone.version);
  assert.deepEqual(registered.layout, standalone.layout);
  assert.deepEqual(registered.sdk_compatibility, standalone.sdk_compatibility);
  assert.deepEqual(registered.interaction_targets, standalone.interaction_targets);
  assert.deepEqual(registered.conformance, standalone.conformance);
  assert.equal(registered.integrity, standalone.integrity);
});
