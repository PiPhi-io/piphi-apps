import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import manifest from "../widget.manifest.json" with { type: "json" };
import catalog from "../widget-capability-catalog.json" with { type: "json" };
import { validateWidgetManifest } from "piphi-network-widget-sdk/manifest";
import {
  layoutTopology,
  lifecycleMessage,
  linkQualityTone,
  normalizeLifecycle,
  normalizeTopology,
} from "../src/topology-model.js";

const fixture = {
  state: {
    zigbee_network_topology: {
      status: "ok",
      collected_at: "2026-10-30T12:00:00Z",
      routes_included: false,
      nodes: [
        { id: "coordinator", friendly_name: "Coordinator", type: "Coordinator", network_address: 0 },
        { id: "router", friendly_name: "Hall router", type: "Router", manufacturer: "Example", model: "R1" },
        { id: "sensor", friendly_name: "Door sensor", type: "EndDevice" },
      ],
      links: [
        { source: "coordinator", target: "router", link_quality: 210 },
        { source: "router", target: "sensor", link_quality: 72 },
      ],
    },
  },
};

test("manifest and capability catalog agree", () => {
  const errors = validateWidgetManifest(manifest).filter((issue) => issue.severity === "error");
  assert.deepEqual(errors, []);
  const consumed = new Set(catalog.rows.filter((row) => row.status === "implemented").flatMap((row) => row.consumes));
  assert.deepEqual(new Set(manifest.capability_requirements), consumed);
  assert.deepEqual(manifest.security.permissions, ["host.executeCommand"]);
  assert.deepEqual(manifest.security.allowed_commands, ["refresh_network_map"]);
  assert.deepEqual(manifest.security.csp.connect_src, []);
});

test("normalizes bounded topology and rejects dangling links", () => {
  const unsafe = structuredClone(fixture);
  unsafe.state.zigbee_network_topology.nodes[2].friendly_name = "Door\u0000 sensor";
  unsafe.state.zigbee_network_topology.links.push({ source: "missing", target: "sensor", link_quality: 999 });
  const topology = normalizeTopology(unsafe);
  assert.equal(topology.nodes.length, 3);
  assert.equal(topology.nodes[2].name, "Door sensor");
  assert.equal(topology.links.length, 2);
  assert.equal(topology.collectedAt, "2026-10-30T12:00:00.000Z");
});

test("lays out coordinator, routers, and end devices deterministically", () => {
  const topology = normalizeTopology(fixture);
  const first = layoutTopology(topology, 760, 420);
  const second = layoutTopology(topology, 760, 420);
  assert.deepEqual(first, second);
  assert.deepEqual(
    first.nodes.find((node) => node.type === "coordinator"),
    { ...topology.nodes[0], x: 380, y: 210 },
  );
  assert.equal(first.links.length, 2);
});

test("covers lifecycle, empty, and link quality states", () => {
  for (const status of ["loading", "live", "stale", "offline", "reconnecting", "denied", "error"]) {
    assert.equal(normalizeLifecycle(status), status);
  }
  assert.equal(normalizeLifecycle("unknown"), "error");
  assert.equal(linkQualityTone(200), "strong");
  assert.equal(linkQualityTone(100), "fair");
  assert.equal(linkQualityTone(40), "weak");
  assert.equal(linkQualityTone(null), "unknown");
  assert.equal(lifecycleMessage("live", normalizeTopology({}), { empty: "Empty", live: "Live" }), "Empty");
});

test("declares keyboard, responsive, theme, RTL, reduced-motion, and manual-scan behavior", () => {
  const source = readFileSync(new URL("../src/widget.js", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../src/widget.css", import.meta.url), "utf8");
  for (const token of ["tabindex=\"0\"", "aria-live", "event.key === \"Enter\"", "localization?.direction", "refresh_network_map", "scanWarning"]) {
    assert.ok(source.includes(token), token);
  }
  for (const token of ["focus-visible", "@media (max-width: 480px)", "color-scheme: light dark", "prefers-reduced-motion", "forced-colors"]) {
    assert.ok(styles.includes(token), token);
  }
});
