import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { formatMetric, lifecycleCopy, normalizeLifecycle, projectState } from "./view-model.js";

const METRICS = [
  { id: "appliance_state", label: "Status", unit: "" },
  { id: "remaining_minutes", label: "Time left", unit: "min" },
  { id: "door", label: "Door", unit: "" },
  { id: "temperature", label: "Temperature", unit: "°C" },
  { id: "target_temperature", label: "Target", unit: "°C" },
  { id: "humidity", label: "Humidity", unit: "%" },
  { id: "pm2", label: "PM2.5", unit: "µg/m³" },
  { id: "filter_life", label: "Filter", unit: "%" },
  { id: "mode", label: "Mode", unit: "" },
  { id: "cycle_count", label: "Cycles", unit: "" },
  { id: "fan_speed", label: "Fan", unit: "" },
  { id: "power", label: "Power", unit: "W" },
  { id: "battery", label: "Battery", unit: "%" },
];
const MAX_GLANCE_METRICS = 4;
const ACCENT = "#a50034";
const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const [initialContext, settings, translatedTitle, waiting] = await Promise.all([
  host.getContext(),
  host.getSettings(),
  host.translate("widget.title"),
  host.translate("widget.waiting"),
]);

root.innerHTML = `
  <style>
    :root { color-scheme: only light; font: 14px/1.45 Inter, ui-sans-serif, system-ui, sans-serif; background: transparent !important; }
    * { box-sizing: border-box; }
    html, body, #piphi-widget-root { margin: 0; background: transparent !important; }
    main { min-height: 0 !important; padding: 10px; color: var(--piphi-widget-text, CanvasText); background: none !important; overflow: hidden; position: relative; }
    header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; min-height: 32px; }
    .mark { display: grid; place-items: center; width: 32px; height: 32px; flex: 0 0 32px; border-radius: 10px; color: white; background: ${ACCENT}; font-weight: 850; letter-spacing: -.03em; }
    h2 { margin: 0; font-size: 1rem; line-height: 1.2; }
    .metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); grid-auto-rows: 48px; gap: 6px; }
    .metric { height: 48px; min-width: 0; padding: 6px 9px; overflow: hidden; border: 1px solid var(--piphi-widget-border, color-mix(in srgb, currentColor 15%, transparent)); border-radius: var(--piphi-widget-radius, 11px); background: var(--piphi-widget-surface-muted, color-mix(in srgb, currentColor 6%, transparent)); }
    .label { display: block; overflow: hidden; color: var(--piphi-widget-text-muted, currentColor); font-size: .72rem; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
    .value { display: block; margin-top: 1px; overflow: hidden; font-size: 1rem; line-height: 1.25; font-weight: 780; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
    .lifecycle { display: flex; align-items: center; gap: 8px; margin: 8px 0 0; min-height: 1.35em; opacity: .76; font-size: .78rem; }
    main[data-state="live"] .lifecycle { display: none; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #8b8b93; }
    main[data-state="live"] .dot { background: #16a36a; box-shadow: 0 0 0 4px color-mix(in srgb, #16a36a 18%, transparent); }
    main[data-state="offline"] .dot, main[data-state="error"] .dot, main[data-state="denied"] .dot { background: #d14343; }
    @media (max-width: 360px) { main { padding: 8px; } .metric { padding-inline: 7px; } }
    @media (max-width: 240px) { .metrics { grid-template-columns: 1fr; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
  </style>
  <main data-state="loading" dir="${escapeHtml(initialContext.localization?.direction || "ltr")}">
    <header><span class="mark" aria-hidden="true">LG</span><h2>${escapeHtml(String(settings.title || (translatedTitle === "widget.title" ? "LG appliance" : translatedTitle)))}</h2></header>
    <section class="metrics" aria-label="LG ThinQ readings">${METRICS.map((metric) => `<div class="metric" hidden><span class="label">${escapeHtml(metric.label)}</span><strong class="value" data-key="${escapeHtml(metric.id)}">—</strong></div>`).join("")}</section>
    <p class="lifecycle" role="status" aria-live="polite"><span class="dot" aria-hidden="true"></span><span data-status>${escapeHtml(waiting === "widget.waiting" ? "Waiting for LG ThinQ data" : waiting)}</span></p>
  </main>`;

const card = root.querySelector("main");
const statusNode = root.querySelector("[data-status]");
const currentState = {};
function contextBindingSlots(value) {
  const candidates = [
    value.bindings,
    value.props?.piphiBindings,
    value.props?.bindingSlots,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length > 0) return candidate;
  }
  const primary = value.binding || value.props?.piphiBinding || value.props?.binding;
  return primary ? [{ id: "primary", role: "primary", binding: primary }] : [];
}

function renderState(data, capabilityIds, lifecycle = "live") {
  Object.assign(currentState, projectState(data, capabilityIds));
  let visibleMetrics = 0;
  for (const metric of METRICS) {
    const node = root.querySelector(`[data-key="${metric.id}"]`);
    const metricCard = node.closest(".metric");
    const hasValue = currentState[metric.id] !== null && currentState[metric.id] !== undefined && currentState[metric.id] !== "";
    const showMetric = hasValue && visibleMetrics < MAX_GLANCE_METRICS;
    metricCard.hidden = !showMetric;
    if (showMetric) visibleMetrics += 1;
    node.textContent = formatMetric(currentState[metric.id], metric.unit);
  }
  const displayLifecycle = lifecycle === "live" && visibleMetrics === 0 ? "empty" : lifecycle;
  card.dataset.state = displayLifecycle;
  statusNode.textContent = lifecycleCopy(displayLifecycle);
}
let activeBindingSignature = "";
let contextGeneration = 0;
let stateStops = [];

let resizeFrame = 0;
let lastReportedHeight = 0;
function reportContentHeight() {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    const nextHeight = Math.ceil(card.scrollHeight);
    if (nextHeight <= 0 || nextHeight === lastReportedHeight) return;
    lastReportedHeight = nextHeight;
    void host.setHeight(nextHeight).catch(() => undefined);
  });
}
const resizeObserver = new ResizeObserver(reportContentHeight);

function clearMetrics() {
  for (const metric of METRICS) delete currentState[metric.id];
  renderState({}, [], "loading");
}

function releaseStateSubscriptions() {
  const previousStops = stateStops;
  stateStops = [];
  for (const stop of previousStops) Promise.resolve(stop()).catch(() => undefined);
}

async function bindContext(context) {
  const slots = contextBindingSlots(context);
  const signature = JSON.stringify(slots.map((slot) => ({
    configId: slot.binding?.configId,
    deviceId: slot.binding?.deviceId || slot.binding?.deviceKey,
    capabilityId: slot.binding?.capabilityId,
  })));
  if (signature === activeBindingSignature) return;
  activeBindingSignature = signature;
  contextGeneration += 1;
  const generation = contextGeneration;
  releaseStateSubscriptions();
  clearMetrics();
  card.dir = context.localization?.direction || "ltr";
  try {
    const capabilityIds = slots
    .map((slot) => slot.binding?.capabilityId)
    .filter((capabilityId) => METRICS.some((metric) => metric.id === capabilityId));
    if (capabilityIds.length === 0) throw new Error("Select an LG ThinQ device for this card");
    renderState(await host.getCapabilityState({ capabilityIds, forceRefresh: true }), capabilityIds);
    if (generation !== contextGeneration) return;
    stateStops.push(await host.subscribeState({ capabilityIds }, (event) => {
      if (generation !== contextGeneration) return;
      const lifecycle = normalizeLifecycle(event.status || event.kind);
      card.dataset.state = lifecycle;
      statusNode.textContent = lifecycleCopy(lifecycle);
      if (event.kind !== "snapshot" && event.kind !== "point") return;
      renderState(event.data, capabilityIds, lifecycle);
    }));
  } catch (error) {
    if (generation !== contextGeneration) return;
    statusNode.textContent = error instanceof Error ? error.message : "Unable to load LG ThinQ bindings";
  }
}

lastReportedHeight = Math.ceil(card.scrollHeight);
await host.ready({ height: lastReportedHeight });
resizeObserver.observe(card);
await bindContext(initialContext);
const stopContext = host.subscribe((context) => { void bindContext(context); });
window.addEventListener("pagehide", () => {
  cancelAnimationFrame(resizeFrame);
  resizeObserver.disconnect();
  stopContext();
  releaseStateSubscriptions();
}, { once: true });

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
