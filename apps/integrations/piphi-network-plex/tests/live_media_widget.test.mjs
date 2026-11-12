import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { mountLiveMediaWidget } from "../widgets/live-media/widget.js";

class Element {
  textContent = ""; children = []; dataset = {}; hidden = true; listeners = {}; scrollHeight = 88; parent = null;
  append(...children) { for (const child of children) child.parent = this; this.children.push(...children); }
  replaceChildren() { this.children = []; }
  replaceWith(next) { const index = this.parent?.children.indexOf(this) ?? -1; if (index >= 0) { next.parent = this.parent; this.parent.children[index] = next; } }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, callback) { this.listeners[key] = callback; }
  removeEventListener(key) { delete this.listeners[key]; }
}
const flush = () => new Promise(setImmediate);
function contrastRatio(foreground, background) {
  const luminance = (hex) => {
    const channels = [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255)
      .map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}
async function setup(initialFailure = "", runtimeWidgetId = "io.piphi.plex.continue-watching", settings = { title: "Movie night", refreshSeconds: 1 }, translations = {}) {
  const nodes = new Map();
  const root = { innerHTML: "", ownerDocument: { createElement: () => new Element() }, querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  } };
  let next = { items: [{ title: "Movie", kind: "movie", duration_seconds: 100, view_offset_seconds: 25 }] };
  let fail = initialFailure;
  let scheduled;
  let count = 0;
  const heights = [];
  const host = {
    getSettings: async () => settings,
    getContext: async () => ({ packageId: "plex-media", package: { id: runtimeWidgetId }, props: { machineId: "home" } }),
    translate: async (key) => translations[key] ?? key,
    ready: async ({ height }) => { heights.push(height); },
    setHeight: async (height) => { heights.push(height); },
    request: async (method, params) => {
      assert.equal(method, "host.queryMedia"); assert.equal(params, undefined); count++;
      if (fail) throw new Error(fail);
      return next;
    },
  };
  const cleanup = await mountLiveMediaWidget(host, root, {
    setTimeout: (callback, delay) => { scheduled = { callback, delay }; return 1; },
    clearTimeout: () => { scheduled = undefined; },
  });
  await flush();
  return { nodes, cleanup, root, heights, setResult(value) { next = value; }, setOffline() { fail = "offline"; },
    get scheduled() { return scheduled; }, get count() { return count; } };
}

test("renders live items, watch progress, and refreshes without accumulating stale rows", async () => {
  const widget = await setup();
  assert.equal(widget.nodes.get("h2").textContent, "Movie night");
  assert.equal(widget.nodes.get("ul").children[0].children[1].children[2].value, 25);
  assert.equal(widget.scheduled.delay, 15000);
  widget.setResult({ items: [{ title: "New movie", kind: "movie" }] });
  widget.scheduled.callback(); await flush();
  assert.equal(widget.nodes.get("ul").children.length, 1);
  assert.equal(widget.nodes.get("ul").children[0].children[1].children[0].textContent, "New movie");
  widget.cleanup(); assert.equal(widget.scheduled, undefined);
});
test("renders brokered artwork without adding another bordered card shell", async () => {
  const widget = await setup();
  widget.setResult({ items: [{ title: "Poster", kind: "movie", artwork_url: "/api/v2/media/poster" }] });
  widget.scheduled.callback(); await flush();
  const artwork = widget.nodes.get("ul").children[0].children[0];
  assert.equal(artwork.className, "artwork");
  assert.equal(artwork.src, "/api/v2/media/poster");
  artwork.listeners.error();
  assert.equal(widget.nodes.get("ul").children[0].children[0].className, "artwork-placeholder");
  assert.doesNotMatch(widget.root.innerHTML, /li \{[^}]*border:/);
  widget.cleanup();
});
test("uses the installed card identity for its default title", async () => {
  const widget = await setup("", "io.piphi/plex-media@0.1.3/library-search", {});
  assert.equal(widget.nodes.get("h2").textContent, "Plex Search / Library");
  widget.cleanup();
});
test("keeps previous results visibly stale on failure and backs off", async () => {
  const widget = await setup(); widget.setOffline();
  widget.scheduled.callback(); await flush();
  assert.equal(widget.nodes.get(".status").dataset.state, "stale");
  assert.equal(widget.nodes.get("ul").children.length, 1);
  assert.equal(widget.scheduled.delay, 30000); widget.cleanup();
});
test("shows empty results and renders untrusted titles as text", async () => {
  const widget = await setup();
  widget.setResult({ items: [{ title: "<script>bad()</script>" }] });
  widget.scheduled.callback(); await flush();
  assert.equal(widget.nodes.get("ul").children[0].children[1].children[0].textContent, "<script>bad()</script>");
  assert.ok(!widget.root.innerHTML.includes("bad()"));
  widget.setResult({ items: [] }); widget.scheduled.callback(); await flush();
  assert.equal(widget.nodes.get(".empty").hidden, false); widget.cleanup();
});
test("initial access denial is distinct from offline and generic errors", async () => {
  for (const [message, state, copy] of [
    ["access denied", "denied", "Plex access needs permission"],
    ["offline", "offline", "Plex is offline · retrying"],
    ["Invalid response", "error", "Plex is unavailable · retrying"],
  ]) {
    const widget = await setup(message);
    assert.equal(widget.nodes.get(".status").dataset.state, state);
    assert.ok(widget.heights.includes(88));
    assert.equal(widget.nodes.get(".status").textContent, copy);
    widget.cleanup();
  }
});
test("localizes canonical Plex media copy while preserving media titles", async () => {
  const translations = {
    "plex.title.continue_watching": "متابعة المشاهدة",
    "plex.action.refresh": "تحديث Plex",
    "plex.media.label": "وسائط Plex",
    "plex.media.kind.movie": "فيلم",
    "plex.media.watched": "تمت مشاهدة %PERCENT%% من %TITLE%",
  };
  const widget = await setup("", "io.piphi.plex.continue-watching", { title:"Continue Watching" }, translations);
  assert.equal(widget.nodes.get("h2").textContent, "متابعة المشاهدة");
  assert.equal(widget.nodes.get("button")["aria-label"], "تحديث Plex");
  assert.equal(widget.nodes.get("ul")["aria-label"], "وسائط Plex");
  const item = widget.nodes.get("ul").children[0].children[1];
  assert.equal(item.children[0].textContent, "Movie");
  assert.equal(item.children[1].textContent, "فيلم");
  assert.equal(item.children[2]["aria-label"], "تمت مشاهدة 25% من Movie");
  widget.cleanup();
});
test("manual refresh works and teardown prevents future polling", async () => {
  const widget = await setup();
  widget.nodes.get("button").listeners.click(); await flush();
  assert.equal(widget.count, 2);
  const pending = widget.scheduled.callback;
  widget.cleanup(); pending(); await flush();
  assert.equal(widget.count, 2);
});
test("declares responsive accessible light and dark behavior", async () => {
  const source = await readFile(new URL("../widgets/live-media/widget.js", import.meta.url), "utf8");
  assert.match(source, /color-scheme:light dark/);
  assert.match(source, /@container \(max-width:320px\)/);
  assert.match(source, /prefers-reduced-motion:reduce/);
  assert.match(source, /forced-colors:active/);
  assert.match(source, /min-height:44px/);
  assert.match(source, /h3 \{[^}]*font-size:\.875rem/);
  assert.match(source, /--plex-control-text:#ffd166/);
  assert.match(source, /setAttribute\("aria-label", copy\.refresh\)/);
  assert.match(source, /role="status" aria-live="polite"/);
  assert.match(source, /setAttribute\("aria-label", copy\.mediaLabel\)/);
  assert.ok(contrastRatio("#704800", "#ffffff") >= 4.5);
  for (const surface of ["#0c1320", "#0f172a", "#172033", "#22304a"]) {
    assert.ok(contrastRatio("#ffd166", surface) >= 4.5);
  }
});
test("experience widgets carry complete certification evidence", async () => {
  const source = JSON.parse(await readFile(
    new URL("../experiences/plex-media/package.source.json", import.meta.url),
    "utf8",
  ));
  for (const widget of source.widgets) {
    const gates = new Set(widget.certification.verified_gates);
    assert.deepEqual(new Set(Object.keys(widget.certification.evidence)), gates);
    for (const gate of ["runtime", "persistence", "states", "responsive", "themes", "accessibility", "save-reload", "performance"]) {
      assert.ok(gates.has(gate), `${widget.id} is missing ${gate}`);
    }
    assert.equal(gates.has("binding"), widget.binding_slots?.length > 0);
    assert.ok(widget.interaction_targets?.length > 0, `${widget.id} is missing semantic interaction targets`);
    assert.equal(widget.presentation?.shell, "core");
    assert.equal(widget.presentation?.content_surface, "transparent");
  }
});
test("every Plex media widget ships matching English and Arabic catalogs", async () => {
  const source = JSON.parse(await readFile(
    new URL("../experiences/plex-media/package.source.json", import.meta.url),
    "utf8",
  ));
  for (const widget of source.widgets.filter((candidate) => candidate.id !== "server-overview")) {
    const english = widget.translations?.en ?? {};
    const arabic = widget.translations?.ar ?? {};
    assert.ok(Object.keys(english).length >= 19, `${widget.id} has an incomplete English catalog`);
    assert.deepEqual(Object.keys(arabic).sort(), Object.keys(english).sort(), `${widget.id} Arabic keys drifted`);
    assert.ok(Object.values(arabic).every((value) => String(value).trim()), `${widget.id} has an empty Arabic translation`);
  }
});
test("all media-query SDK bundles have correct SRI and no unresolved package imports", async () => {
  for (const name of ["recently-added", "continue-watching", "library-search"]) {
    const base = new URL(`../widgets/${name}/`, import.meta.url);
    const manifest = JSON.parse(await readFile(new URL("widget.manifest.json", base), "utf8"));
    const bundle = await readFile(new URL("dist/widget.js", base));
    assert.equal(manifest.integrity, `sha384-${createHash("sha384").update(bundle).digest("base64")}`);
    assert.ok(bundle.toString().includes("getInjectedPiPhiWidgetHost"));
    assert.ok(!/from ["']piphi-network-widget-sdk/.test(bundle.toString()));
    assert.deepEqual(manifest.security.permissions, ["host.queryMedia"]);
    assert.equal(manifest.sdk_compatibility.minimum, "0.6.0");
    assert.equal(manifest.layout.default_height, 112);
    assert.ok(manifest.interaction_targets?.length > 0);
    assert.equal(manifest.interaction_targets.filter((target) => target.kind === "card").length, 1);
  }
});
test("server overview bundle has correct SRI and no unresolved package imports", async () => {
  const base = new URL("../widgets/plex-server-overview/", import.meta.url);
  const manifest = JSON.parse(await readFile(new URL("widget.manifest.json", base), "utf8"));
  const bundle = await readFile(new URL("dist/widget.js", base));
  assert.equal(manifest.integrity, `sha384-${createHash("sha384").update(bundle).digest("base64")}`);
  assert.ok(bundle.toString().includes("getInjectedPiPhiWidgetHost"));
  assert.ok(!/from ["']piphi-network-widget-sdk/.test(bundle.toString()));
  assert.deepEqual(manifest.security.permissions, []);
  assert.equal(manifest.sdk_compatibility.minimum, "0.6.0");
  assert.ok(bundle.toString().includes("createRecoverySession"));
  assert.ok(manifest.interaction_targets?.length > 0);
});
