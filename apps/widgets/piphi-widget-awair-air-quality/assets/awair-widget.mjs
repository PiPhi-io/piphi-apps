// node_modules/piphi-network-widget-sdk/dist/client.js
function getInjectedPiPhiWidgetHost(widgetWindow) {
  const resolvedWindow = widgetWindow ?? (typeof window !== "undefined" ? window : void 0);
  if (!resolvedWindow) {
    throw new Error("The PiPhi Widget SDK requires a browser window.");
  }
  const host = resolvedWindow.PiPhiWidgetHost;
  if (!host) {
    throw new Error("PiPhiWidgetHost is not available. Run this widget inside a PiPhi dashboard or create a client bridge.");
  }
  return host;
}

// src/widget.ts
var METRICS = [
  ["co2", "CO\u2082", "ppm"],
  ["pm25", "PM2.5", "\xB5g/m\xB3"],
  ["voc", "VOC", "ppb"],
  ["temperature", "Temperature", "\xB0"],
  ["humidity", "Humidity", "%"]
];
function scoreBand(raw) {
  const score = Number(raw);
  if (!Number.isFinite(score)) return { label: "Waiting for data", tone: "unknown" };
  if (score >= 90) return { label: "Excellent", tone: "excellent" };
  if (score >= 80) return { label: "Good", tone: "good" };
  if (score >= 60) return { label: "Fair", tone: "fair" };
  return { label: "Needs attention", tone: "poor" };
}
function formatReading(reading, fallbackUnit = "") {
  if (!reading || reading.value === null || reading.value === void 0 || reading.value === "") return "\u2014";
  const numeric = Number(reading.display ?? reading.value);
  const display = Number.isFinite(numeric) ? new Intl.NumberFormat(void 0, { maximumFractionDigits: 1 }).format(numeric) : String(reading.display ?? reading.value);
  const unit = reading.unit || fallbackUnit;
  return unit ? `${display} ${unit}` : display;
}
function statesFromEvent(event, fallbackSlotId) {
  const rows = event?.kind === "snapshot" ? Array.isArray(event.data?.states) ? event.data.states : [] : event?.kind === "point" && event.data ? [event.data] : [];
  return rows.flatMap((row) => {
    if (row?.found === false) return [];
    const id = String(row?.slotId ?? row?.slot_id ?? row?.capabilityId ?? row?.capability_id ?? fallbackSlotId ?? "").trim();
    if (!id) return [];
    return [{
      id,
      reading: {
        value: row.value,
        display: row.displayValue ?? row.display_value,
        unit: row.unit,
        collectedAt: row.ts ?? row.collected_at ?? row.received_at
      }
    }];
  });
}
function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function stale(readings, status) {
  if (["stale", "offline", "unavailable"].includes(status)) return true;
  const timestamps = [...readings.values()].map((reading) => typeof reading.collectedAt === "number" ? reading.collectedAt : Date.parse(String(reading.collectedAt ?? ""))).filter(Number.isFinite).map((value) => value < 1e12 ? value * 1e3 : value);
  return timestamps.length > 0 && Date.now() - Math.max(...timestamps) > 12e4;
}
var CSS = `<style>
  .awair { container-type: inline-size; display:grid; gap:12px; color:var(--piphi-widget-text,#172033); }
  .awair__hero { display:grid; grid-template-columns:auto 1fr; gap:14px; align-items:center; padding:14px; border:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 14%,transparent)); border-radius:var(--piphi-widget-radius,16px); background:var(--piphi-widget-surface,color-mix(in srgb,currentColor 5%,transparent)); }
  .awair__score { display:grid; place-items:center; width:76px; height:76px; border-radius:50%; font-size:1.75rem; font-weight:800; background:color-mix(in srgb,var(--awair-tone,#14b8a6) 16%,transparent); color:var(--awair-tone,#0f766e); }
  .awair[data-tone="fair"] { --awair-tone:#d97706; } .awair[data-tone="poor"] { --awair-tone:#dc2626; } .awair[data-tone="unknown"] { --awair-tone:#64748b; }
  .awair__eyebrow,.awair__status { margin:0; color:var(--piphi-widget-text-muted,#64748b); font-size:.72rem; font-weight:700; }
  .awair__title { margin:3px 0; font-size:1.08rem; }
  .awair__metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
  .awair__metric { min-width:0; padding:10px; border:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 12%,transparent)); border-radius:12px; background:transparent; color:inherit; text-align:left; font:inherit; cursor:pointer; }
  .awair__metric:hover,.awair__metric:focus-visible { border-color:var(--awair-tone,#14b8a6); outline:none; }
  .awair__metric span { display:block; color:var(--piphi-widget-text-muted,#64748b); font-size:.68rem; }
  .awair__metric strong { display:block; margin-top:4px; overflow:hidden; text-overflow:ellipsis; font-size:.95rem; }
  .awair__message { margin:0; padding:12px; border-radius:12px; background:color-mix(in srgb,#dc2626 10%,transparent); color:#b91c1c; font-size:.82rem; }
  .awair__skeleton { min-height:150px; border-radius:16px; background:linear-gradient(100deg,transparent 20%,color-mix(in srgb,currentColor 9%,transparent) 40%,transparent 60%); background-size:220% 100%; animation:awair-shimmer 1.4s infinite; }
  @container (max-width:340px) { .awair__metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  @container (max-width:230px) { .awair__hero { grid-template-columns:1fr; } .awair__score { width:60px; height:60px; font-size:1.35rem; } .awair__metrics { grid-template-columns:1fr; } }
  @keyframes awair-shimmer { to { background-position:-220% 0; } }
  @media (prefers-reduced-motion:reduce) { .awair__skeleton { animation:none; } }
</style>`;
function mountAwairWidget(root, host) {
  const readings = /* @__PURE__ */ new Map();
  const subscriptions = [];
  let bootstrap = null;
  let phase = "loading";
  let status = "";
  let message = "";
  const height = () => Math.max(180, root.scrollHeight || 180);
  const render = () => {
    if (phase === "loading") {
      root.innerHTML = `${CSS}<section class="awair" aria-label="Awair air quality" aria-busy="true"><div class="awair__skeleton" aria-label="Loading air-quality readings"></div></section>`;
      return;
    }
    if (phase === "error") {
      root.innerHTML = `${CSS}<section class="awair" aria-label="Awair air quality"><p class="awair__message" role="alert">${escapeHtml(message)}</p></section>`;
      return;
    }
    const score = readings.get("score");
    const band = scoreBand(score?.value);
    const isStale = stale(readings, status);
    const metricButtons = METRICS.map(([id, label, unit]) => `<button class="awair__metric" type="button" data-target="${id}" aria-label="View ${label} details"><span>${label}</span><strong>${formatReading(readings.get(id), unit)}</strong></button>`).join("");
    const emptyMessage = phase === "empty" ? `<p class="awair__message" role="status">No readings are available yet. Check the device connection and refresh.</p>` : "";
    root.innerHTML = `${CSS}<section class="awair" data-tone="${band.tone}" aria-label="Awair air quality">
      <div class="awair__hero"><div class="awair__score" aria-label="Air quality score ${escapeHtml(formatReading(score))}">${escapeHtml(formatReading(score))}</div><div><p class="awair__eyebrow">Awair Element</p><h2 class="awair__title">${band.label}</h2><p class="awair__status">${isStale ? "Last known reading \xB7 updates delayed" : "Indoor air quality \xB7 live"}</p></div></div>
      ${emptyMessage}<div class="awair__metrics">${metricButtons}</div>
    </section>`;
    root.querySelectorAll("[data-target]").forEach((element) => element.addEventListener("click", () => {
      void host.activateInteraction(String(element.dataset.target)).catch((error) => {
        phase = "error";
        message = error instanceof Error ? error.message : "Unable to open air-quality details.";
        render();
      });
    }));
    queueMicrotask(() => void host.setHeight(height()));
  };
  const connect = async (next) => {
    bootstrap = next;
    phase = "loading";
    render();
    for (const unsubscribe of subscriptions.splice(0)) await unsubscribe().catch(() => void 0);
    readings.clear();
    const bindings = bootstrap.bindings ?? [];
    if (!bindings.length) {
      phase = "empty";
      render();
      await host.ready({ height: height() });
      return;
    }
    try {
      for (const slot of bindings) {
        const unsubscribe = await host.subscribeState({ slotId: slot.id }, (event) => {
          if (event?.kind === "error") {
            phase = "error";
            message = event.error?.message || "Live readings are unavailable.";
          } else if (event?.kind === "status") {
            status = String(event.status ?? event.data?.status ?? "").toLowerCase();
            phase = readings.size ? "ready" : "empty";
          } else {
            for (const row of statesFromEvent(event, slot.id)) readings.set(row.id, row.reading);
            phase = readings.size ? "ready" : "empty";
          }
          render();
        });
        subscriptions.push(unsubscribe);
      }
      await host.ready({ height: height() });
    } catch (error) {
      phase = "error";
      message = error instanceof Error ? error.message : "Unable to load air-quality readings.";
      render();
      await host.ready({ height: height() });
    }
  };
  render();
  const unsubscribeBootstrap = host.subscribe((next) => void connect(next));
  return async () => {
    unsubscribeBootstrap();
    for (const unsubscribe of subscriptions.splice(0)) await unsubscribe().catch(() => void 0);
  };
}
if (typeof window !== "undefined" && typeof document !== "undefined" && window.PiPhiWidgetHost) {
  const root = document.getElementById("piphi-widget-root");
  if (root) mountAwairWidget(root, getInjectedPiPhiWidgetHost(window));
}
export {
  formatReading,
  mountAwairWidget,
  scoreBand,
  statesFromEvent
};
