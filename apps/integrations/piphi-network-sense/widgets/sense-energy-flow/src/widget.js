import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { createSenseStateReducer, describeSenseStreamEvent } from "./state.js";

const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const context = await host.getContext();
const title = await host.translate("widget.title");

root.innerHTML = `
  <style>
    :root { color-scheme: light dark; --sense-flow-solar:#08784b; font:var(--piphi-widget-font-size,14px)/1.4 var(--piphi-widget-font-family,system-ui,sans-serif); }
    :root[data-piphi-color-scheme=dark] { --sense-flow-solar:#6ee7b7; }
    * { box-sizing:border-box; }
    main { min-height:0; padding:4px; color:var(--piphi-widget-text,#0f172a); background:transparent; overflow:hidden; }
    h2 { margin:0 0 8px; font-size:1rem; line-height:1.25; }
    .flow { min-height:64px; display:grid; grid-template-columns:1fr auto 1fr; gap:8px; align-items:center; padding:6px 4px; border-inline-start:2px solid var(--piphi-widget-accent,#ff5b35); }
    .value { font-size:clamp(1.5rem,7vw,2.25rem); line-height:1.05; font-weight:750; font-variant-numeric:tabular-nums; }
    .solar { text-align:end; color:var(--sense-flow-solar); }
    .arrow { font-size:1.35rem; color:var(--piphi-widget-text-muted,#52647a); }
    .daily { display:grid; grid-template-columns:1fr 1fr; gap:0; margin-top:6px; padding-top:6px; border-top:1px solid var(--piphi-widget-border,#d7dee8); }
    .daily div { min-width:0; min-height:44px; padding:4px 8px; }
    .daily div + div { border-inline-start:1px solid var(--piphi-widget-border,#d7dee8); }
    small,[role=status] { color:var(--piphi-widget-text-muted,#52647a); font-size:.75rem; }
    [role=status][hidden] { display:none; }
    @container (max-width:260px) { .arrow { display:none; } .flow { grid-template-columns:1fr 1fr; } }
    @media (forced-colors:active) { .flow,.daily,.daily div + div { border-color:CanvasText; } }
  </style>
  <main dir="${context.localization?.direction || "ltr"}">
    <h2>${escapeHtml(title)}</h2>
    <section class="flow" aria-label="Current power flow">
      <div><small>Home</small><div class="value" data-key="active_power_w">—</div><small>W</small></div>
      <span class="arrow" aria-hidden="true">⇄</span>
      <div class="solar"><small>Solar</small><div class="value" data-key="active_solar_power_w">—</div><small>W</small></div>
    </section>
    <section class="daily">
      <div><small>Used today</small><strong data-key="daily_usage_kwh">—</strong> kWh</div>
      <div><small>Produced today</small><strong data-key="daily_production_kwh">—</strong> kWh</div>
    </section>
    <p role="status" hidden>Waiting for Sense data</p>
  </main>`;

const status = root.querySelector("[role=status]");
const stateReducer = createSenseStateReducer();
const stop = await host.subscribeState(
  { capabilityIds: ["active_power_w", "active_solar_power_w", "daily_usage_kwh", "daily_production_kwh"] },
  (event) => {
    const stream = describeSenseStreamEvent(event);
    status.hidden = stream.hidden;
    status.textContent = stream.message;
    const state = stateReducer.apply(event).values;
    if (event.kind !== "snapshot" && event.kind !== "point") {
      syncHeight();
      return;
    }
    for (const node of root.querySelectorAll("[data-key]")) {
      const value = state[node.dataset.key];
      if (value !== undefined && value !== null) node.textContent = formatNumber(value);
    }
    syncHeight();
  },
);

window.addEventListener("pagehide", stop, { once: true });
await host.ready({ height: 156 });

function syncHeight() {
  const measured = Number(root.querySelector("main")?.scrollHeight);
  void host.setHeight?.(Math.min(240, Math.max(112, measured || 156)));
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(number) : "—";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
