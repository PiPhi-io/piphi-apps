import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { validateDeclarativeWidgetRecipe } from "piphi-network-widget-sdk/declarative";

const source = JSON.parse(readFileSync(new URL("../package.source.json", import.meta.url), "utf8"));

test("package identity and integration linkage are stable", () => {
  assert.deepEqual(source.identity, {
    publisher_id: "io.piphi",
    package_id: "kasa-smart-home",
    version: "0.1.17",
  });
  assert.equal(source.owning_integration_id, "tp-link-kasa-local-api");
  assert.deepEqual(source.recommended_for_integrations, ["tp-link-kasa-local-api"]);
  assert.equal(source.requires_integrations[0].integration_id, "tp-link-kasa-local-api");
});

test("sandboxed widgets are authored against and bundled from the Widget SDK", () => {
  const widgetSource = readFileSync(new URL("../src/widget.ts", import.meta.url), "utf8");
  const metricsSource = readFileSync(new URL("../src/metrics-widget.ts", import.meta.url), "utf8");
  const bundle = readFileSync(new URL("../assets/kasa-widget.mjs", import.meta.url), "utf8");
  assert.match(widgetSource, /from "piphi-network-widget-sdk"/);
  assert.match(widgetSource, /getInjectedPiPhiWidgetHost/);
  assert.match(widgetSource, /createOptimisticControl/);
  assert.match(metricsSource, /from "piphi-network-widget-sdk"/);
  assert.ok(source.widgets.every((widget) => widget.runtime === "sandboxed_bundle"));
  assert.doesNotMatch(bundle, /from "piphi-network-widget-sdk"/);
  assert.equal(existsSync(new URL("../assets/optimistic-control.mjs", import.meta.url)), false);
});

test("all declared assets exist and declarative recipes pass the SDK", () => {
  for (const widget of source.widgets) {
    if (widget.entry) assert.equal(existsSync(new URL(`../${widget.entry}`, import.meta.url)), true);
    for (const theme of widget.themes ?? []) {
      assert.equal(existsSync(new URL(`../${theme.stylesheet}`, import.meta.url)), true);
    }
    if (widget.runtime === "declarative") {
      const diagnostics = validateDeclarativeWidgetRecipe(widget.recipe, {
        bindingSlotIds: widget.binding_slots.map((slot) => slot.id),
        settingIds: (widget.settings ?? []).map((setting) => setting.id),
      });
      assert.deepEqual(diagnostics, []);
    }
  }
});

test("command widgets request permission and use an explicit allow-list", () => {
  for (const widget of source.widgets.filter((candidate) => candidate.allowed_commands?.length)) {
    assert.deepEqual(widget.permissions, ["host.executeCommand"]);
    assert.ok(widget.allowed_commands.length > 0);
  }
});
