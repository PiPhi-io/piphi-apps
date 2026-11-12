import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import {
  layoutTopology,
  lifecycleMessage,
  linkQualityTone,
  normalizeLifecycle,
  normalizeTopology,
} from "./topology-model.js";

const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const [context, settings, title, waiting, empty, scanLabel, scanningLabel, scanWarning, retryLabel] = await Promise.all([
  host.getContext(),
  host.getSettings(),
  host.translate("widget.title"),
  host.translate("widget.waiting"),
  host.translate("widget.empty"),
  host.translate("widget.scan"),
  host.translate("widget.scanning"),
  host.translate("widget.scan_warning"),
  host.translate("widget.retry"),
]);

let topology = normalizeTopology({});
let lifecycle = "loading";
let selectedId = null;
let working = false;
let zoom = 1;
let panX = 0;
let panY = 0;
let drag = null;

root.innerHTML = `
  <main class="network-map" dir="${escapeHtml(context.localization?.direction || "ltr")}">
    <header class="map-header">
      <div>
        <h2>${escapeHtml(String(settings.title || title))}</h2>
        <p class="summary" aria-live="polite">${escapeHtml(waiting)}</p>
      </div>
      <button class="scan-button" type="button" aria-describedby="scan-warning">${escapeHtml(scanLabel)}</button>
    </header>
    <p id="scan-warning" class="scan-warning">${escapeHtml(scanWarning)}</p>
    <div class="toolbar" aria-label="Map controls">
      <button type="button" data-map-action="zoom-in" aria-label="Zoom in">+</button>
      <button type="button" data-map-action="zoom-out" aria-label="Zoom out">−</button>
      <button type="button" data-map-action="reset">Reset</button>
      <span class="legend"><i class="coordinator"></i>Coordinator <i class="router"></i>Router <i class="end-device"></i>End device</span>
    </div>
    <div class="map-stage">
      <svg class="topology" viewBox="0 0 760 420" role="img" aria-label="Zigbee network topology"></svg>
      <div class="state-panel" role="status"></div>
    </div>
    <aside class="inspector" aria-live="polite" hidden></aside>
  </main>`;

const svg = root.querySelector(".topology");
const summary = root.querySelector(".summary");
const statusPanel = root.querySelector(".state-panel");
const inspector = root.querySelector(".inspector");
const scanButton = root.querySelector(".scan-button");

root.querySelector(".toolbar").addEventListener("click", (event) => {
  const action = event.target.closest("button")?.dataset.mapAction;
  if (!action) return;
  if (action === "zoom-in") zoom = Math.min(2.5, zoom + 0.2);
  if (action === "zoom-out") zoom = Math.max(0.55, zoom - 0.2);
  if (action === "reset") [zoom, panX, panY] = [1, 0, 0];
  applyViewport();
});

svg.addEventListener("wheel", (event) => {
  event.preventDefault();
  zoom = Math.max(0.55, Math.min(2.5, zoom + (event.deltaY < 0 ? 0.12 : -0.12)));
  applyViewport();
}, { passive: false });
svg.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".node")) return;
  drag = { x: event.clientX, y: event.clientY, panX, panY };
  svg.setPointerCapture(event.pointerId);
});
svg.addEventListener("pointermove", (event) => {
  if (!drag) return;
  panX = drag.panX + (event.clientX - drag.x) / zoom;
  panY = drag.panY + (event.clientY - drag.y) / zoom;
  applyViewport();
});
svg.addEventListener("pointerup", () => { drag = null; });

scanButton.addEventListener("click", scanNetwork);

const stop = await host.subscribeState({ capabilityIds: ["zigbee_network_topology"] }, (event) => {
  lifecycle = normalizeLifecycle(event.status || event.kind);
  if (event.kind === "snapshot" || event.kind === "point") topology = normalizeTopology(event.data);
  render();
});
window.addEventListener("pagehide", stop, { once: true });
render();
await host.ready({ height: 520 });

async function scanNetwork() {
  if (working) return;
  working = true;
  scanButton.disabled = true;
  scanButton.textContent = scanningLabel;
  summary.textContent = scanWarning;
  try {
    const result = await host.executeCommand({
      commandName: "refresh_network_map",
      args: { routes: settings.include_routes === true },
    });
    if (result?.topology) topology = normalizeTopology(result.topology);
    else topology = normalizeTopology(await host.getCapabilityState({ forceRefresh: true }));
    lifecycle = "live";
  } catch (error) {
    lifecycle = "error";
    summary.textContent = safeError(error);
  } finally {
    working = false;
    scanButton.disabled = false;
    scanButton.textContent = lifecycle === "error" ? retryLabel : scanLabel;
    render();
    scanButton.focus();
  }
}

function render() {
  const message = lifecycleMessage(lifecycle, topology, {
    loading: waiting,
    empty,
    denied: "The widget does not have access to this bridge.",
    error: "The network map could not be loaded.",
    offline: "The bridge is offline. Last known map shown.",
    stale: "This map may be out of date.",
    live: `${topology.nodes.length} devices · ${topology.links.length} links`,
  });
  summary.textContent = message;
  statusPanel.textContent = topology.nodes.length ? "" : message;
  statusPanel.hidden = topology.nodes.length > 0;
  svg.hidden = topology.nodes.length === 0;
  if (!topology.nodes.length) {
    inspector.hidden = true;
    return;
  }

  const layout = layoutTopology(topology);
  svg.innerHTML = `<g class="viewport"><g class="links">${layout.links.map(renderLink).join("")}</g><g class="nodes">${layout.nodes.map(renderNode).join("")}</g></g>`;
  applyViewport();
  svg.querySelectorAll(".node").forEach((node) => {
    node.addEventListener("click", () => selectNode(node.dataset.nodeId));
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectNode(node.dataset.nodeId);
      }
    });
    node.addEventListener("dblclick", () => void host.activateInteraction("topology-details"));
  });
  if (selectedId) selectNode(selectedId, false);
}

function renderLink(link) {
  const quality = Number.isFinite(link.linkQuality) ? link.linkQuality : null;
  const label = settings.show_link_quality !== false && quality !== null ? `<text x="${(link.sourceNode.x + link.targetNode.x) / 2}" y="${(link.sourceNode.y + link.targetNode.y) / 2 - 5}">${quality}</text>` : "";
  return `<g class="link ${linkQualityTone(quality)}"><line x1="${link.sourceNode.x}" y1="${link.sourceNode.y}" x2="${link.targetNode.x}" y2="${link.targetNode.y}" />${label}</g>`;
}

function renderNode(node) {
  const role = node.type === "end-device" ? "End device" : capitalize(node.type);
  const selected = node.id === selectedId ? " selected" : "";
  return `<g class="node ${node.type}${selected}" transform="translate(${node.x} ${node.y})" tabindex="0" role="button" data-node-id="${escapeHtml(node.id)}" aria-label="${escapeHtml(`${node.name}, ${role}`)}"><circle r="19"></circle><text class="glyph" y="5">${node.type === "coordinator" ? "C" : node.type === "router" ? "R" : "E"}</text><text class="node-label" y="35">${escapeHtml(node.name)}</text></g>`;
}

function selectNode(id, focus = true) {
  const node = topology.nodes.find((candidate) => candidate.id === id);
  if (!node) return;
  selectedId = id;
  svg.querySelectorAll(".node").forEach((element) => element.classList.toggle("selected", element.dataset.nodeId === id));
  const identifier = settings.show_identifiers === true
    ? `<dt>Identifier</dt><dd>${escapeHtml(node.ieeeAddress || String(node.networkAddress ?? "Unknown"))}</dd>`
    : "";
  inspector.innerHTML = `<div><strong>${escapeHtml(node.name)}</strong><span>${escapeHtml(node.type === "end-device" ? "End device" : capitalize(node.type))}</span></div><dl>${identifier}<dt>Manufacturer</dt><dd>${escapeHtml(node.manufacturer || "Unknown")}</dd><dt>Model</dt><dd>${escapeHtml(node.model || "Unknown")}</dd></dl>`;
  inspector.hidden = false;
  if (focus) inspector.scrollIntoView({ block: "nearest" });
}

function applyViewport() {
  const viewport = svg.querySelector(".viewport");
  if (viewport) viewport.setAttribute("transform", `translate(${panX} ${panY}) scale(${zoom})`);
}

function safeError(error) {
  return String(error?.message || "The scan failed. Check the bridge and try again.").replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 240);
}

function capitalize(value) { return String(value).replace(/^./, (letter) => letter.toUpperCase()); }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }
