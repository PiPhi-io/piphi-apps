import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { formatStatus, normalizeLifecycle, projectState } from "./model.js";

const CAPABILITIES = ["connected", "simulation_mode", "print_status", "print_progress_percent", "remaining_time_minutes", "current_layer", "total_layers", "nozzle_temperature_c", "bed_temperature_c"];
const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const [context, settings, defaultTitle] = await Promise.all([
  host.getContext(), host.getSettings(), host.translate("widget.title"),
]);
const title = String(settings.title || defaultTitle || "Bambu printer");
const direction = context.localization?.direction === "rtl" ? "rtl" : "ltr";

root.innerHTML = `
  <style>
    :root { color-scheme: light dark; font: 14px/1.4 Inter, ui-sans-serif, system-ui, sans-serif; }
    * { box-sizing: border-box; }
    main { min-height: 154px; padding: 18px; border-radius: 18px; background: Canvas; color: CanvasText; }
    h2, p { margin: 0; }
    h2 { font-size: .88rem; font-weight: 650; }
    .simulation { margin-inline-start: 8px; font-size: .72rem; font-weight: 500; opacity: .65; }
    .status { margin-top: 17px; font-size: 1.15rem; font-weight: 650; }
    .progress { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-top: 4px; font-size: .8rem; }
    .muted { opacity: .68; }
    progress { display: block; width: 100%; height: 8px; margin-top: 11px; accent-color: #18a99e; }
    .meta { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 10px; font-size: .78rem; }
    [role=status] { margin-top: 8px; color: #b54736; font-size: .76rem; }
    [role=status]:empty, [hidden] { display: none !important; }
    main:focus-visible { outline: 2px solid #2675df; outline-offset: -3px; }
    @media (max-width: 360px) { main { padding: 14px; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }
  </style>
  <main tabindex="0" aria-label="${escapeHtml(title)}" dir="${direction}" data-state="loading">
    <h2>${escapeHtml(title)}<span class="simulation" data-simulation hidden>Simulation</span></h2>
    <p class="status" data-print-status>Waiting for printer</p>
    <div class="progress"><span class="muted" data-remaining></span><strong data-percent></strong></div>
    <progress max="100" value="0" aria-label="Print progress" hidden></progress>
    <div class="meta muted"><span data-layers></span><span data-nozzle></span><span data-bed></span></div>
    <p role="status" aria-live="polite" data-error></p>
  </main>`;

const card = root.querySelector("main");
const error = root.querySelector("[data-error]");
const progress = root.querySelector("progress");
const stop = await host.subscribeState({ capabilityIds: CAPABILITIES }, (event) => {
  const lifecycle = normalizeLifecycle(event.status || event.kind);
  card.dataset.state = lifecycle;
  if (event.kind === "snapshot" || event.kind === "point") {
    const state = projectState(event.data);
    root.querySelector("[data-simulation]").hidden = !state.simulation_mode;
    root.querySelector("[data-print-status]").textContent = formatStatus(state.print_status);
    const percent = state.print_progress_percent;
    progress.hidden = percent === null;
    progress.value = percent ?? 0;
    root.querySelector("[data-percent]").textContent = percent === null ? "" : `${Math.round(percent)}%`;
    root.querySelector("[data-remaining]").textContent = state.remaining_time_minutes === null ? "" : `${Math.round(state.remaining_time_minutes)} min remaining`;
    root.querySelector("[data-layers]").textContent = state.current_layer === null || state.total_layers === null ? "" : `Layer ${state.current_layer}/${state.total_layers}`;
    root.querySelector("[data-nozzle]").textContent = state.nozzle_temperature_c === null ? "" : `Nozzle ${Math.round(state.nozzle_temperature_c)}°C`;
    root.querySelector("[data-bed]").textContent = state.bed_temperature_c === null ? "" : `Bed ${Math.round(state.bed_temperature_c)}°C`;
    error.textContent = !state.connected ? "Printer offline" : lifecycle === "stale" ? "Printer data may be old" : "";
  } else {
    error.textContent = lifecycle === "live" || lifecycle === "loading" ? "" : lifecycle;
  }
});
window.addEventListener("pagehide", stop, { once: true });
await host.ready({ height: 200 });

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
