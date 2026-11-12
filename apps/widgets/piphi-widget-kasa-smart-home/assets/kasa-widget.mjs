// node_modules/piphi-network-widget-sdk/dist/client.js
function getInjectedPiPhiWidgetHost(widgetWindow) {
  const resolvedWindow = widgetWindow ?? (typeof window !== "undefined" ? window : void 0);
  if (!resolvedWindow) {
    throw new Error("The PiPhi Widget SDK requires a browser window.");
  }
  const host2 = resolvedWindow.PiPhiWidgetHost;
  if (!host2) {
    throw new Error("PiPhiWidgetHost is not available. Run this widget inside a PiPhi dashboard or create a client bridge.");
  }
  return host2;
}

// node_modules/piphi-network-widget-sdk/dist/optimistic-control.js
function readingTime(raw) {
  if (raw == null || raw === "")
    return null;
  const parsed = typeof raw === "number" ? raw : /^\d+$/.test(raw) ? Number(raw) : Date.parse(raw);
  if (!Number.isFinite(parsed))
    return null;
  return parsed < 1e12 ? parsed * 1e3 : parsed;
}
function createOptimisticControl(options = {}) {
  let confirmed = options.initial;
  let override = null;
  let lastReadingAt = 0;
  let confirmationTimer = null;
  const now = options.now ?? Date.now;
  const equals = options.equals ?? Object.is;
  const confirmationMs = Math.max(1, options.confirmationMs ?? 1e4);
  const visible = () => override?.value ?? confirmed;
  const notify = () => options.onChange?.(visible());
  const clearTimer = () => {
    if (confirmationTimer)
      clearTimeout(confirmationTimer);
    confirmationTimer = null;
  };
  return {
    get value() {
      return visible();
    },
    get confirmed() {
      return confirmed;
    },
    get pending() {
      return override?.pending ?? false;
    },
    get awaitingConfirmation() {
      return override !== null && !override.pending;
    },
    begin(next) {
      clearTimer();
      override = { value: next, issuedAt: now(), pending: true };
      notify();
    },
    accept() {
      if (!override)
        return;
      override.pending = false;
      const accepted = override;
      clearTimer();
      confirmationTimer = setTimeout(() => {
        if (override !== accepted)
          return;
        override = null;
        confirmationTimer = null;
        notify();
      }, confirmationMs);
      notify();
    },
    reject() {
      clearTimer();
      override = null;
      notify();
    },
    observe(value2, observedAt) {
      const timestamp = readingTime(observedAt);
      if (timestamp !== null && timestamp < lastReadingAt)
        return;
      if (timestamp === null && lastReadingAt > 0 && (!override || !equals(value2, override.value)))
        return;
      if (timestamp !== null)
        lastReadingAt = timestamp;
      confirmed = value2;
      if (override && (equals(value2, override.value) || !override.pending && timestamp !== null && timestamp >= override.issuedAt)) {
        override = null;
        clearTimer();
      }
      notify();
    },
    reset(value2) {
      clearTimer();
      confirmed = value2;
      override = null;
      lastReadingAt = 0;
      notify();
    },
    destroy() {
      clearTimer();
      override = null;
    }
  };
}

// src/widget.ts
var root = typeof document === "undefined" ? null : document.getElementById("piphi-widget-root");
var host = typeof window === "undefined" ? null : getInjectedPiPhiWidgetHost(window);
var state = {
  bootstrap: null,
  values: /* @__PURE__ */ new Map(),
  error: "",
  errorSource: "",
  pending: "",
  subscriptions: [],
  bindingScope: "",
  ready: false,
  brightnessEditing: false
};
var powerControl = createOptimisticControl({
  onChange: () => {
    if (!state.brightnessEditing) render();
  }
});
var brightnessControl = createOptimisticControl({
  onChange: () => {
    if (!state.brightnessEditing) render();
  }
});
function normalizeBoolean(value2) {
  if (typeof value2 === "boolean") return value2;
  if (typeof value2 === "number") return value2 !== 0;
  const normalized = String(value2 ?? "").trim().toLowerCase();
  return ["1", "true", "on", "yes", "active"].includes(normalized);
}
function formatReading(value2, unit, maximumFractionDigits = 2) {
  if (value2 === null || value2 === void 0 || value2 === "") return "\u2014";
  const numeric = Number(value2);
  const display = Number.isFinite(numeric) ? new Intl.NumberFormat(void 0, { maximumFractionDigits }).format(numeric) : String(value2);
  return unit ? `${display} ${unit}` : display;
}
function statesFromEvent(event) {
  if (event?.kind === "snapshot") return Array.isArray(event.data?.states) ? event.data.states : [];
  if (event?.kind === "point" && event.data) {
    return [{
      capability_id: event.data.capabilityId ?? event.data.capability_id,
      value: event.data.value,
      display_value: event.data.displayValue ?? event.data.display_value,
      unit: event.data.unit,
      collected_at: event.data.ts ?? event.data.collected_at,
      found: true
    }];
  }
  return [];
}
function commandForPower(value2) {
  return normalizeBoolean(value2) ? "turn_off" : "turn_on";
}
function escapeHtml(value2) {
  return String(value2 ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function widgetMode() {
  const id = String(state.bootstrap?.package?.id ?? "");
  return id.endsWith("/smart-plug") ? "smart-plug" : "device-control";
}
function cardTargetForMode(mode) {
  return mode === "smart-plug" ? "smart-plug-card" : "device-card";
}
async function activateTarget(targetId, widgetHost = host) {
  if (!widgetHost?.activateInteraction) return void 0;
  return widgetHost.activateInteraction(targetId);
}
function setting(name, fallback = true) {
  const value2 = state.bootstrap?.settings?.[name];
  return typeof value2 === "boolean" ? value2 : fallback;
}
function contentHeight() {
  const content = root?.querySelector(".kasa");
  const minimum = widgetMode() === "device-control" ? 128 : 180;
  return Math.max(minimum, content?.scrollHeight ?? root?.scrollHeight ?? minimum);
}
function updateValues(event) {
  for (const item of statesFromEvent(event)) {
    const id = String(item.capability_id ?? item.capabilityId ?? "").trim();
    if (!id || item.found === false) continue;
    state.values.set(id, {
      value: item.value,
      display: item.display_value ?? item.displayValue,
      unit: item.unit
    });
    const observedAt = item.collected_at ?? item.received_at;
    if (id === "switch") powerControl.observe(normalizeBoolean(item.value), observedAt);
    if (id === "brightness" && Number.isFinite(Number(item.value))) {
      brightnessControl.observe(Number(item.value), observedAt);
    }
  }
}
function value(id) {
  return state.values.get(id)?.value;
}
function reading(id, fallbackUnit) {
  const item = state.values.get(id);
  return formatReading(item?.display ?? item?.value, item?.unit ?? fallbackUnit);
}
function styles() {
  return `<style>
    .kasa { display: grid; align-content: start; min-height: 0; gap: var(--piphi-experience-gap, 10px); padding: 2px; color: var(--piphi-widget-text, #172033); }
    .kasa__hero, .kasa__tile { border: 1px solid var(--piphi-experience-tile-border, color-mix(in srgb, currentColor 14%, transparent)); background: var(--piphi-experience-tile-surface, color-mix(in srgb, currentColor 5%, transparent)); border-radius: var(--piphi-experience-radius, 16px); box-shadow: var(--piphi-experience-tile-shadow, none); }
    .kasa__hero { display: grid; gap: 10px; min-height: 82px; padding: 13px 14px; overflow: hidden; isolation: isolate; }
    .kasa__hero[data-active="true"] { background: linear-gradient(112deg, color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 13%, var(--piphi-experience-tile-surface, transparent)), var(--piphi-experience-tile-surface, transparent) 68%); }
    .kasa__hero-main { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-width: 0; }
    .kasa__identity { min-width: 0; flex: 1; align-self: stretch; display: grid; align-content: center; padding: 0; border: 0; background: transparent; color: inherit; text-align: start; cursor: pointer; }
    .kasa__identity:hover .kasa__title, .kasa__brightness-details:hover .kasa__brightness-label { color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__eyebrow { margin: 0 0 5px; color: var(--piphi-widget-text-muted, #64748b); font-size: .65rem; font-weight: 800; letter-spacing: .105em; text-transform: uppercase; }
    .kasa__title { margin: 0; font-size: 1.02rem; line-height: 1.18; font-weight: 780; transition: color .16s ease; }
    .kasa__state { display: flex; align-items: center; gap: 6px; margin: 5px 0 0; color: var(--piphi-widget-text-muted, #64748b); font-size: .75rem; font-weight: 620; }
    .kasa__state-dot { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: color-mix(in srgb, currentColor 38%, transparent); }
    .kasa__hero[data-active="true"] .kasa__state-dot { background: var(--piphi-experience-accent, #14b8a6); box-shadow: 0 0 0 3px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 13%, transparent); }
    .kasa__power { display: grid; place-items: center; width: 46px; height: 46px; flex: 0 0 46px; border: 1px solid color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 24%, transparent); border-radius: 15px; background: color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 11%, transparent); color: var(--piphi-experience-accent, #0f766e); cursor: pointer; transition: transform .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease; }
    .kasa__power svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 2.25; }
    .kasa__power[aria-pressed="true"] { border-color: transparent; background: var(--piphi-experience-accent, #14b8a6); color: white; box-shadow: 0 9px 24px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 30%, transparent); }
    .kasa__power:hover:not(:disabled) { transform: translateY(-1px) scale(1.025); box-shadow: 0 10px 24px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 22%, transparent); }
    .kasa__power:active:not(:disabled) { transform: translateY(0) scale(.97); }
    .kasa__power:disabled { cursor: wait; opacity: .68; }
    .kasa__brightness { display: grid; gap: 5px; padding-top: 9px; border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent); }
    .kasa__brightness-details { display: grid; grid-template-columns: 1fr auto; gap: 12px; padding: 0; border: 0; background: transparent; color: inherit; text-align: start; cursor: pointer; }
    .kasa__brightness-label { font-size: .78rem; font-weight: 700; transition: color .16s ease; }
    .kasa__brightness-value { color: var(--piphi-widget-text-muted, #64748b); font-size: .78rem; font-variant-numeric: tabular-nums; }
    .kasa__brightness input { width: 100%; min-height: 18px; margin: 0; accent-color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__section-title { margin: 2px 2px -2px; color: var(--piphi-widget-text-muted, #64748b); font-size: .72rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
    .kasa__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--piphi-experience-gap, 12px); }
    .kasa__tile { min-width: 0; padding: 11px 12px; cursor: pointer; text-align: start; color: inherit; font: inherit; }
    .kasa__tile:hover { border-color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__metric-label { display: block; color: var(--piphi-widget-text-muted, #64748b); font-size: .72rem; }
    .kasa__metric-value { display: block; margin-top: 4px; font-size: 1.12rem; font-weight: 780; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .kasa__metric-value--energy { color: var(--piphi-experience-energy-accent, #d97706); }
    .kasa__message { margin: 0; padding: 10px 12px; border-radius: 12px; background: color-mix(in srgb, #dc2626 10%, transparent); color: #b91c1c; font-size: .82rem; }
    @container (max-width: 360px) { .kasa__metrics { grid-template-columns: 1fr 1fr; } .kasa__metrics > :first-child { grid-column: 1 / -1; } }
    @container (max-width: 250px) { .kasa__hero { gap: 8px; padding-inline: 11px; } .kasa__hero-main { gap: 10px; } .kasa__power { width: 42px; height: 42px; flex-basis: 42px; border-radius: 13px; } }
    @media (prefers-reduced-motion: reduce) { .kasa__power { transition: none; } }
  </style>`;
}
function energyTile(id, label, unit, targetId, accent = false) {
  return `<button class="kasa__tile" type="button" data-target="${targetId}">
    <span class="kasa__metric-label">${label}</span>
    <strong class="kasa__metric-value${accent ? " kasa__metric-value--energy" : ""}">${reading(id, unit)}</strong>
  </button>`;
}
function render() {
  if (!root) return;
  const mode = widgetMode();
  const cardTarget = cardTargetForMode(mode);
  const isOn = powerControl.value ?? normalizeBoolean(value("switch"));
  const brightness = brightnessControl.value ?? Number(value("brightness"));
  const showBrightness = mode === "device-control" && Number.isFinite(brightness);
  const energy = mode === "smart-plug" ? `<p class="kasa__section-title">Energy use</p><div class="kasa__metrics">
        ${energyTile("energy_power", "Right now", "W", "smart-plug-energy", true)}
        ${setting("show_today") ? energyTile("energy_today", "Today", "kWh", "smart-plug-energy") : ""}
        ${setting("show_month") ? energyTile("energy_this_month", "This month", "kWh", "smart-plug-energy") : ""}
      </div>` : "";
  root.innerHTML = `${styles()}<section class="kasa" aria-label="Kasa ${mode === "smart-plug" ? "smart plug" : "device control"}">
    <div class="kasa__hero" data-active="${isOn}">
      <div class="kasa__hero-main">
        <button class="kasa__identity" type="button" data-target="${cardTarget}" aria-label="View Kasa device details"><p class="kasa__eyebrow">Kasa device</p><h2 class="kasa__title">Power</h2><p class="kasa__state"><span class="kasa__state-dot" aria-hidden="true"></span><span>${isOn ? "On" : "Off"}</span></p></button>
        <button class="kasa__power" type="button" aria-label="Turn ${isOn ? "off" : "on"}" aria-pressed="${isOn}" ${state.pending ? "disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"></path><path d="M6.3 5.8a8 8 0 1 0 11.4 0"></path></svg></button>
      </div>
      ${showBrightness ? `<div class="kasa__brightness"><button class="kasa__brightness-details" type="button" data-target="${cardTarget}" aria-label="View brightness details"><span class="kasa__brightness-label">Brightness</span><output class="kasa__brightness-value" for="brightness">${Math.round(brightness)}%</output></button><input id="brightness" type="range" min="0" max="100" step="1" value="${Math.round(brightness)}" aria-label="Brightness" ${state.pending ? "disabled" : ""}></div>` : ""}
    </div>
    ${energy}
    ${state.error ? `<p class="kasa__message" role="alert">${escapeHtml(state.error)}</p>` : ""}
  </section>`;
  root.querySelector(".kasa__power")?.addEventListener("click", () => runCommand(commandForPower(isOn), {}, "power", powerControl, !isOn));
  root.querySelector("#brightness")?.addEventListener("input", (event) => {
    state.brightnessEditing = true;
    root.querySelector(".kasa__brightness-value").textContent = `${Number(event.currentTarget.value)}%`;
  });
  root.querySelector("#brightness")?.addEventListener("change", (event) => {
    state.brightnessEditing = false;
    const brightness2 = Number(event.currentTarget.value);
    void runCommand("set_brightness", { brightness: brightness2 }, "brightness", brightnessControl, brightness2);
  });
  root.querySelectorAll("[data-target]").forEach((element) => element.addEventListener("click", () => {
    void activateTarget(element.dataset.target).catch((error) => {
      state.error = error instanceof Error ? error.message : "Unable to open device details.";
      render();
    });
  }));
  if (state.ready) {
    queueMicrotask(() => void host?.setHeight(contentHeight()));
  }
}
async function runCommand(commandName, args = {}, slotId = "power", control = null, target) {
  if (!host || state.pending) return;
  state.pending = commandName;
  state.error = "";
  state.errorSource = "";
  if (control) control.begin(target);
  render();
  try {
    await host.executeCommand({ commandName, args, slotId });
    control?.accept();
  } catch (error) {
    control?.reject();
    state.error = error instanceof Error ? error.message : "The device did not respond. Try again.";
    state.errorSource = "command";
  } finally {
    state.pending = "";
    render();
  }
}
async function connect(bootstrap) {
  state.bootstrap = bootstrap;
  render();
  if (!state.ready) {
    await host.ready({ height: contentHeight() });
    state.ready = true;
  }
  const bindings = Array.isArray(bootstrap?.bindings) ? bootstrap.bindings : [];
  const bindingScope = bindings.map((slot) => [slot.id, slot.binding?.configId, slot.binding?.deviceKey, slot.binding?.capabilityId].join(":")).join("|");
  if (state.bindingScope === bindingScope && state.subscriptions.length) return;
  for (const unsubscribe of state.subscriptions.splice(0)) {
    try {
      await unsubscribe();
    } catch {
    }
  }
  state.bindingScope = bindingScope;
  state.error = "";
  state.errorSource = "";
  state.values.clear();
  state.brightnessEditing = false;
  powerControl.reset();
  brightnessControl.reset();
  for (const slot of bindings) {
    try {
      const unsubscribe = await host.subscribeState({ slotId: slot.id }, (event) => {
        if (event?.kind === "error") {
          if (state.errorSource !== "command") {
            state.error = event.error?.message || "Live updates are temporarily unavailable.";
            state.errorSource = "stream";
          }
        } else {
          if (state.errorSource === "stream") {
            state.error = "";
            state.errorSource = "";
          }
          updateValues(event);
        }
        if (!state.brightnessEditing) render();
      });
      state.subscriptions.push(unsubscribe);
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Unable to load device state.";
      state.errorSource = "stream";
      render();
    }
  }
}
if (root && host) {
  host.subscribe((bootstrap) => void connect(bootstrap));
}
export {
  activateTarget,
  cardTargetForMode,
  commandForPower,
  formatReading,
  normalizeBoolean,
  statesFromEvent
};
