import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const source = JSON.parse(readFileSync(new URL("../package.source.json", import.meta.url), "utf8"));

test("package identity and integration linkage are stable", () => {
  assert.deepEqual(source.identity, {
    publisher_id: "io.piphi",
    package_id: "awair-air-quality",
    version: "0.1.16",
  });
  assert.equal(source.owning_integration_id, "awair-element-local-api");
  assert.deepEqual(source.recommended_for_integrations, ["awair-element-local-api"]);
  assert.equal(source.requires_integrations[0].integration_id, "awair-element-local-api");
});

test("the package points at a built SDK widget", () => {
  assert.equal(source.widgets.length, 1);
  const widget = source.widgets[0];
  assert.equal(widget.runtime, "sandboxed_bundle");
  assert.equal(widget.entry, "assets/awair-widget.mjs");
  assert.equal(existsSync(new URL(`../${widget.entry}`, import.meta.url)), true);
  const authored = readFileSync(new URL("../src/widget.ts", import.meta.url), "utf8");
  const bundle = readFileSync(new URL(`../${widget.entry}`, import.meta.url), "utf8");
  assert.match(authored, /from "piphi-network-widget-sdk"/);
  assert.match(authored, /getInjectedPiPhiWidgetHost/);
  assert.doesNotMatch(bundle, /from "piphi-network-widget-sdk"/);
});

test("the widget is read-only and requests no browser or command permissions", () => {
  const widget = source.widgets[0];
  assert.deepEqual(widget.permissions ?? [], []);
  assert.deepEqual(widget.allowed_commands ?? [], []);
  assert.ok(widget.binding_slots.every((slot) => slot.binding_modes.length === 1 && slot.binding_modes[0] === "read"));
  assert.ok(widget.binding_slots.every((slot) => slot.allow_shared_device === true));
});
