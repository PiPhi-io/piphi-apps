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

// src/metrics-widget.ts
var CONFIG = {
  energy: {
    label: "Kasa energy monitor",
    eyebrow: "Energy use",
    metrics: [
      ["live-power", "Right now", "W"],
      ["today", "Today", "kWh"],
      ["month", "This month", "kWh"]
    ]
  },
  environment: {
    label: "Kasa environment monitor",
    eyebrow: "Room comfort",
    metrics: [
      ["temperature", "Temperature", "\xB0"],
      ["humidity", "Humidity", "%"]
    ]
  }
};
function modeForPackageId(packageId) {
  return String(packageId ?? "").endsWith("/environment-monitor") ? "environment" : "energy";
}
function formatMetric(reading, fallbackUnit) {
  if (!reading || reading.value === null || reading.value === void 0 || reading.value === "") return "\u2014";
  const numeric = Number(reading.display ?? reading.value);
  const display = Number.isFinite(numeric) ? new Intl.NumberFormat(void 0, { maximumFractionDigits: 2 }).format(numeric) : String(reading.display ?? reading.value);
  return `${display}${reading.unit || fallbackUnit ? ` ${reading.unit || fallbackUnit}` : ""}`;
}
function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function mountKasaMetricsWidget(root, host) {
  const readings = /* @__PURE__ */ new Map();
  const unsubscribers = [];
  let bootstrap = null;
  let phase = "loading";
  let message = "";
  const configuration = () => CONFIG[modeForPackageId(bootstrap?.package?.id)];
  const render = () => {
    const config = configuration();
    const css = `<style>
      .kasa-metrics{container-type:inline-size;display:grid;gap:10px;color:var(--piphi-widget-text,#172033)}
      .kasa-metrics__head{display:flex;align-items:center;justify-content:space-between;gap:10px}.kasa-metrics__head p{margin:0;color:var(--piphi-widget-text-muted,#64748b);font-size:.7rem;font-weight:750;letter-spacing:.08em;text-transform:uppercase}
      .kasa-metrics__grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.kasa-metrics__tile{min-width:0;padding:13px;border:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 13%,transparent));border-radius:14px;background:var(--piphi-widget-surface,color-mix(in srgb,currentColor 5%,transparent));color:inherit;text-align:left;font:inherit;cursor:pointer}.kasa-metrics__tile:hover,.kasa-metrics__tile:focus-visible{border-color:var(--piphi-experience-accent,#14b8a6);outline:none}.kasa-metrics__tile span{display:block;color:var(--piphi-widget-text-muted,#64748b);font-size:.7rem}.kasa-metrics__tile strong{display:block;margin-top:5px;overflow:hidden;text-overflow:ellipsis;font-size:1.14rem}
      .kasa-metrics__message{margin:0;padding:12px;border-radius:12px;background:color-mix(in srgb,#dc2626 10%,transparent);color:#b91c1c;font-size:.82rem}.kasa-metrics__loading{min-height:110px;border-radius:14px;background:color-mix(in srgb,currentColor 7%,transparent)}
      @container(max-width:320px){.kasa-metrics__grid{grid-template-columns:1fr 1fr}.kasa-metrics__grid>:first-child{grid-column:1/-1}}@container(max-width:210px){.kasa-metrics__grid{grid-template-columns:1fr}.kasa-metrics__grid>:first-child{grid-column:auto}}
    </style>`;
    if (phase === "loading") {
      root.innerHTML = `${css}<section class="kasa-metrics" aria-label="${config.label}" aria-busy="true"><div class="kasa-metrics__loading" aria-label="Loading readings"></div></section>`;
      return;
    }
    if (phase === "error") {
      root.innerHTML = `${css}<section class="kasa-metrics" aria-label="${config.label}"><p class="kasa-metrics__message" role="alert">${escapeHtml(message)}</p></section>`;
      return;
    }
    const tiles = config.metrics.map(([id, label, unit]) => `<button class="kasa-metrics__tile" type="button" data-slot="${id}" aria-label="View ${label} history"><span>${label}</span><strong>${formatMetric(readings.get(id), unit)}</strong></button>`).join("");
    const empty = phase === "empty" ? '<p class="kasa-metrics__message" role="status">No readings are available yet.</p>' : "";
    root.innerHTML = `${css}<section class="kasa-metrics" aria-label="${config.label}"><header class="kasa-metrics__head"><p>${config.eyebrow}</p></header>${empty}<div class="kasa-metrics__grid">${tiles}</div></section>`;
    root.querySelectorAll("[data-slot]").forEach((element) => element.addEventListener("click", () => void host.activateInteraction(String(element.dataset.slot))));
    queueMicrotask(() => void host.setHeight(Math.max(140, root.scrollHeight || 140)));
  };
  const connect = async (next) => {
    bootstrap = next;
    phase = "loading";
    readings.clear();
    render();
    for (const unsubscribe of unsubscribers.splice(0)) await unsubscribe().catch(() => void 0);
    const bindings = next.bindings ?? [];
    if (!bindings.length) phase = "empty";
    try {
      for (const slot of bindings) {
        const unsubscribe = await host.subscribeState({ slotId: slot.id }, (event) => {
          if (event?.kind === "error") {
            phase = "error";
            message = event.error?.message || "Live readings are unavailable.";
          } else {
            const states = event?.kind === "snapshot" ? event.data?.states : event?.kind === "point" ? [event.data] : [];
            for (const row of Array.isArray(states) ? states : []) {
              if (!row || row.found === false) continue;
              const id = String(row.slotId ?? row.slot_id ?? row.capabilityId ?? row.capability_id ?? slot.id);
              readings.set(id, { value: row.value, display: row.displayValue ?? row.display_value, unit: row.unit });
            }
            phase = readings.size ? "ready" : "empty";
          }
          render();
        });
        unsubscribers.push(unsubscribe);
      }
    } catch (error) {
      phase = "error";
      message = error instanceof Error ? error.message : "Unable to load readings.";
      render();
    }
    render();
    await host.ready({ height: Math.max(140, root.scrollHeight || 140) });
  };
  render();
  const unsubscribeBootstrap = host.subscribe((next) => void connect(next));
  return async () => {
    unsubscribeBootstrap();
    for (const unsubscribe of unsubscribers.splice(0)) await unsubscribe().catch(() => void 0);
  };
}
if (typeof window !== "undefined" && typeof document !== "undefined" && window.PiPhiWidgetHost) {
  const root = document.getElementById("piphi-widget-root");
  if (root) mountKasaMetricsWidget(root, getInjectedPiPhiWidgetHost(window));
}
export {
  formatMetric,
  modeForPackageId,
  mountKasaMetricsWidget
};
