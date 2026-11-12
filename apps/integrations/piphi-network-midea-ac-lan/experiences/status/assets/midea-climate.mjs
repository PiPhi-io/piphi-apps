const root = typeof document === "undefined" ? null : document.getElementById("piphi-widget-root");
const host = typeof window === "undefined" ? null : window.PiPhiWidgetHost;

const state = {
  bootstrap: null,
  values: new Map(),
  optimistic: new Map(),
  subscriptions: [],
  bindingScope: "",
  pending: "",
  error: "",
  ready: false,
  editingTarget: false,
};

const modes = ["auto", "cool", "heat", "dry", "fan_only"];
const fanModes = ["auto", "silent", "low", "medium", "high", "max"];
const swingModes = ["off", "vertical", "horizontal", "both"];
const presetModes = ["none", "sleep", "eco", "boost", "away"];

export function normalizeBoolean(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  return ["1", "true", "on", "yes", "active", "running"].includes(String(value ?? "").trim().toLowerCase());
}

export function clampTarget(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 22;
  return Math.round(Math.min(30, Math.max(16, numeric)) * 2) / 2;
}

export function statesFromEvent(event) {
  if (event?.kind === "snapshot") return Array.isArray(event.data?.states) ? event.data.states : [];
  if (event?.kind === "point" && event.data) {
    return [{
      capability_id: event.data.capabilityId ?? event.data.capability_id,
      value: event.data.value,
      display_value: event.data.displayValue ?? event.data.display_value,
      unit: event.data.unit,
      found: true,
    }];
  }
  return [];
}

export function commandForTarget(value) {
  return { commandName: "set_target_temperature", args: { temperature: clampTarget(value) }, slotId: "target" };
}

export function commandForFanMode(value) {
  return { commandName: "set_fan_mode", args: { fan_mode: String(value) }, slotId: "fan-mode" };
}

export function commandForSwingMode(value) {
  return { commandName: "set_swing_mode", args: { swing_mode: String(value) }, slotId: "swing" };
}

export function commandForPresetMode(value) {
  return { commandName: "set_preset_mode", args: { preset_mode: String(value) }, slotId: "preset" };
}

export function stateSubscriptionParams(bindings) {
  const capabilityIds = Array.from(new Set(
    (Array.isArray(bindings) ? bindings : [])
      .map((slot) => String(slot?.binding?.capabilityId ?? "").trim())
      .filter(Boolean),
  ));
  return { capabilityIds };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function value(capability, fallback) {
  return state.optimistic.has(capability)
    ? state.optimistic.get(capability)
    : (state.values.get(capability)?.value ?? fallback);
}

function numberValue(capability) {
  const numeric = Number(value(capability, Number.NaN));
  return Number.isFinite(numeric) ? numeric : null;
}

function formattedTemperature(capability, fallback = "—") {
  const numeric = numberValue(capability);
  return numeric === null ? fallback : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(numeric)}°`;
}

function modeLabel(mode) {
  return mode === "fan_only" ? "Fan" : `${String(mode || "auto").charAt(0).toUpperCase()}${String(mode || "auto").slice(1)}`;
}

function titleLabel(value) {
  const text = String(value || "");
  if (!text) return "—";
  if (text === "fan_only") return "Fan";
  return text.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function hasValue(capability) {
  return state.values.has(capability) || state.optimistic.has(capability);
}

function selectOptions(options, current) {
  const normalized = String(current || "");
  const values = options.includes(normalized) ? options : [normalized, ...options].filter(Boolean);
  return values.map((option) => "<option value=\"" + escapeHtml(option) + "\"" + (option === normalized ? " selected" : "") + ">" + escapeHtml(titleLabel(option)) + "</option>").join("");
}

function supportedOptions(capability, fallback) {
  const raw = String(value(capability, "") || "").trim();
  if (!raw) return fallback;
  return raw.split(",").map((option) => option.trim()).filter(Boolean);
}

function presetsForMode(mode, supported) {
  const allowed = {
    auto: ["none", "sleep", "eco", "boost"],
    cool: ["none", "sleep", "eco", "boost"],
    heat: ["none", "sleep", "boost", "away"],
    dry: ["none", "eco"],
    fan_only: ["none"],
  }[mode] || ["none"];
  return supported.filter((preset) => allowed.includes(preset));
}

function matchesOptimistic(capability, observed, expected) {
  if (capability === "power") return normalizeBoolean(observed) === normalizeBoolean(expected);
  if (capability === "target_temperature_c") return Math.abs(Number(observed) - Number(expected)) < 0.01;
  return String(observed) === String(expected);
}

function updateValues(event) {
  for (const item of statesFromEvent(event)) {
    const capability = String(item.capability_id ?? item.capabilityId ?? "").trim();
    if (!capability || item.found === false) continue;
    state.values.set(capability, { value: item.value, display: item.display_value, unit: item.unit });
    if (state.optimistic.has(capability) && matchesOptimistic(capability, item.value, state.optimistic.get(capability))) {
      state.optimistic.delete(capability);
    }
  }
}

function styles() {
  return `<style>
    .midea { --accent: var(--piphi-experience-accent, #38bdf8); display: grid; gap: 9px; min-width: 0; box-sizing: border-box; padding: var(--piphi-widget-space-2, 8px); color: var(--piphi-widget-text, #e5eefb); container-type: inline-size; }
    .midea__top { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 10px; }
    .midea__identity { min-width: 0; padding: 0; border: 0; background: transparent; color: inherit; text-align: start; cursor: pointer; }
    .midea__eyebrow { margin: 0 0 2px; color: var(--piphi-widget-text-muted, #94a3b8); font-size: .64rem; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
    .midea__room { margin: 0; font-size: clamp(2rem, 11cqi, 3rem); line-height: 1; font-weight: 760; letter-spacing: -.055em; font-variant-numeric: tabular-nums; }
    .midea__mode { margin: 5px 0 0; color: var(--piphi-widget-text-muted, #94a3b8); font-size: .74rem; font-weight: 650; }
    .midea__power { display: grid; place-items: center; width: 44px; height: 44px; border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent); border-radius: 14px; background: color-mix(in srgb, var(--accent) 10%, transparent); color: var(--accent); cursor: pointer; transition: transform .15s ease, background .15s ease, box-shadow .15s ease; }
    .midea__power svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-width: 2.2; }
    .midea__power[aria-pressed="true"] { border-color: transparent; background: var(--accent); color: #062638; box-shadow: 0 8px 22px color-mix(in srgb, var(--accent) 28%, transparent); }
    .midea__power:hover:not(:disabled) { transform: translateY(-1px); }
    .midea__power:active:not(:disabled) { transform: scale(.96); }
    .midea__power:disabled, .midea button:disabled, .midea input:disabled { opacity: .58; cursor: wait; }
    .midea__target { display: grid; grid-template-columns: 38px minmax(0, 1fr) 38px; align-items: center; gap: 8px; padding: 10px; border-radius: 16px; background: color-mix(in srgb, currentColor 4%, transparent); }
    .midea__step { width: 38px; height: 38px; border: 1px solid color-mix(in srgb, currentColor 14%, transparent); border-radius: 12px; background: color-mix(in srgb, currentColor 4%, transparent); color: inherit; font-size: 1.25rem; cursor: pointer; }
    .midea__target-center { display: grid; gap: 5px; min-width: 0; text-align: center; }
    .midea__target-label { display: flex; align-items: baseline; justify-content: center; gap: 6px; color: var(--piphi-widget-text-muted, #94a3b8); font-size: .7rem; font-weight: 700; }
    .midea__target-value { color: var(--piphi-widget-text, #e5eefb); font-size: 1.15rem; font-weight: 780; font-variant-numeric: tabular-nums; }
    .midea__target input { width: 100%; min-height: 20px; margin: 0; accent-color: var(--accent); cursor: pointer; }
    .midea__modes { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 5px; }
    .midea__mode-button { min-width: 0; padding: 7px 4px; border: 0; border-radius: 9px; background: color-mix(in srgb, currentColor 4%, transparent); color: var(--piphi-widget-text-muted, #94a3b8); font: inherit; font-size: .68rem; font-weight: 720; cursor: pointer; }
    .midea__mode-button[aria-pressed="true"] { background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
    .midea__features { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
    .midea__feature { display: grid; gap: 3px; min-width: 0; color: var(--piphi-widget-text-muted, #94a3b8); font-size: .62rem; font-weight: 720; }
    .midea__feature select { min-width: 0; width: 100%; height: 34px; padding: 0 24px 0 9px; border: 0; border-radius: 10px; background: color-mix(in srgb, currentColor 6%, transparent); color: var(--piphi-widget-text, #e5eefb); font: inherit; font-size: .7rem; font-weight: 720; cursor: pointer; }
    .midea__feature select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .midea__metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
    .midea__metric { min-width: 0; padding: 7px 9px; border: 0; border-radius: 10px; background: color-mix(in srgb, currentColor 2.5%, transparent); color: inherit; text-align: start; cursor: pointer; }
    .midea__metric span { display: block; color: var(--piphi-widget-text-muted, #94a3b8); font-size: .65rem; }
    .midea__metric strong { display: block; margin-top: 2px; font-size: .9rem; font-variant-numeric: tabular-nums; }
    .midea__error { margin: 0; padding: 9px 11px; border-radius: 11px; background: color-mix(in srgb, #ef4444 13%, transparent); color: #fca5a5; font-size: .74rem; }
    @container (max-width: 270px) { .midea__modes { grid-template-columns: repeat(3, 1fr); } .midea__features { grid-template-columns: 1fr; } .midea__target { grid-template-columns: 34px minmax(0, 1fr) 34px; padding-inline: 8px; } .midea__step { width: 34px; height: 34px; } }
    @media (prefers-color-scheme: light) { .midea { color: var(--piphi-widget-text, #132238); } .midea__power[aria-pressed="true"] { color: white; } }
    @media (prefers-reduced-motion: reduce) { .midea__power { transition: none; } }
  </style>`;
}

function render() {
  if (!root) return;
  const connected = normalizeBoolean(value("connected", true));
  const powered = normalizeBoolean(value("power", false));
  const mode = String(value("hvac_mode", "auto"));
  const action = String(value("hvac_action", "idle"));
  const target = clampTarget(value("target_temperature_c", 22));
  const fanMode = String(value("fan_mode", "auto"));
  const swingMode = String(value("swing_mode", "off"));
  const presetMode = String(value("preset_mode", "none"));
  const availableFanModes = supportedOptions("fan_modes_supported", fanModes);
  const availableSwingModes = supportedOptions("swing_modes_supported", swingModes);
  const availablePresetModes = presetsForMode(
    mode,
    supportedOptions("preset_modes_supported", presetModes),
  );
  const outdoor = numberValue("outdoor_temperature_c");
  const fan = numberValue("fan_speed_percent");
  const optionalMetrics = [
    outdoor === null ? "" : `<button class="midea__metric" type="button" data-target="outdoor-reading"><span>Outside</span><strong>${formattedTemperature("outdoor_temperature_c")}</strong></button>`,
    fan === null ? "" : `<button class="midea__metric" type="button" data-target="fan-reading"><span>Fan speed</span><strong>${Math.round(fan)}%</strong></button>`,
  ].join("");
  const featureControls = [
    hasValue("fan_mode") && availableFanModes.length ? '<label class="midea__feature">Fan<select data-control="fan" aria-label="Fan mode"' + (state.pending || !connected ? " disabled" : "") + ">" + selectOptions(availableFanModes, fanMode) + "</select></label>" : "",
    hasValue("swing_mode") && availableSwingModes.some((item) => item !== "off") ? '<label class="midea__feature">Swing<select data-control="swing" aria-label="Swing mode"' + (state.pending || !connected ? " disabled" : "") + ">" + selectOptions(availableSwingModes, swingMode) + "</select></label>" : "",
    hasValue("preset_mode") && availablePresetModes.length > 1 ? '<label class="midea__feature">Preset<select data-control="preset" aria-label="Comfort preset"' + (state.pending || !connected ? " disabled" : "") + ">" + selectOptions(availablePresetModes, presetMode) + "</select></label>" : "",
  ].join("");
  root.innerHTML = `${styles()}<section class="midea" aria-label="Midea climate control">
    <div class="midea__top">
      <button class="midea__identity" type="button" data-target="indoor-reading" aria-label="View indoor temperature history">
        <p class="midea__eyebrow">Current temperature</p>
        <h2 class="midea__room">${formattedTemperature("indoor_temperature_c")}</h2>
        <p class="midea__mode">${powered ? `${titleLabel(action)} · ${modeLabel(mode)} · Target ${target}°` : "Off"}</p>
      </button>
      <button class="midea__power" type="button" aria-label="Turn ${powered ? "off" : "on"}" aria-pressed="${powered}" ${state.pending || !connected ? "disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"></path><path d="M6.3 5.8a8 8 0 1 0 11.4 0"></path></svg></button>
    </div>
    <div class="midea__target">
      <button class="midea__step" type="button" data-step="-0.5" aria-label="Decrease target temperature" ${state.pending || !connected ? "disabled" : ""}>−</button>
      <div class="midea__target-center">
        <label class="midea__target-label" for="midea-target"><span>Target</span><output class="midea__target-value" for="midea-target">${target}°</output></label>
        <input id="midea-target" type="range" min="16" max="30" step="0.5" value="${target}" aria-label="Target temperature" ${state.pending || !connected ? "disabled" : ""}>
      </div>
      <button class="midea__step" type="button" data-step="0.5" aria-label="Increase target temperature" ${state.pending || !connected ? "disabled" : ""}>+</button>
    </div>
    <div class="midea__modes" aria-label="HVAC mode">${modes.map((item) => `<button class="midea__mode-button" type="button" data-mode="${item}" aria-pressed="${mode === item}" ${state.pending || !connected ? "disabled" : ""}>${modeLabel(item)}</button>`).join("")}</div>
    ${featureControls ? `<div class="midea__features">${featureControls}</div>` : ""}
    ${optionalMetrics ? `<div class="midea__metrics">${optionalMetrics}</div>` : ""}
    ${!connected && !state.error ? `<p class="midea__error" role="status">The air conditioner is offline.</p>` : ""}
    ${state.error ? `<p class="midea__error" role="alert">${escapeHtml(state.error)}</p>` : ""}
  </section>`;

  root.querySelector(".midea__power")?.addEventListener("click", () => void runCommand("set_power", { power: !powered }, "power", "power", !powered));
  root.querySelectorAll("[data-step]").forEach((button) => button.addEventListener("click", () => {
    const next = clampTarget(target + Number(button.dataset.step));
    void runCommand("set_target_temperature", { temperature: next }, "target", "target_temperature_c", next);
  }));
  root.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
    const next = button.dataset.mode;
    if (next !== mode) void runCommand("set_hvac_mode", { mode: next }, "mode", "hvac_mode", next);
  }));
  root.querySelector('[data-control="fan"]')?.addEventListener("change", (event) => {
    const next = event.currentTarget.value;
    void runCommand("set_fan_mode", { fan_mode: next }, "fan-mode", "fan_mode", next);
  });
  root.querySelector('[data-control="swing"]')?.addEventListener("change", (event) => {
    const next = event.currentTarget.value;
    void runCommand("set_swing_mode", { swing_mode: next }, "swing", "swing_mode", next);
  });
  root.querySelector('[data-control="preset"]')?.addEventListener("change", (event) => {
    const next = event.currentTarget.value;
    void runCommand("set_preset_mode", { preset_mode: next }, "preset", "preset_mode", next);
  });
  const slider = root.querySelector("#midea-target");
  slider?.addEventListener("input", (event) => {
    state.editingTarget = true;
    root.querySelector(".midea__target-value").textContent = `${clampTarget(event.currentTarget.value)}°`;
  });
  slider?.addEventListener("change", (event) => {
    state.editingTarget = false;
    const next = clampTarget(event.currentTarget.value);
    void runCommand("set_target_temperature", { temperature: next }, "target", "target_temperature_c", next);
  });
  root.querySelectorAll("[data-target]").forEach((element) => element.addEventListener("click", () => {
    void host?.activateInteraction?.(element.dataset.target).catch((error) => {
      state.error = error instanceof Error ? error.message : "Unable to open climate details.";
      render();
    });
  }));
  // The Core shell owns a one-pixel border on both block edges. Include that
  // allowance in the height report so the final metric row is never clipped.
  if (state.ready) queueMicrotask(() => void host?.setHeight(Math.max(220, root.scrollHeight + 2)));
}

async function runCommand(commandName, args, slotId, capability, optimisticValue) {
  if (!host || state.pending) return;
  state.pending = commandName;
  state.error = "";
  state.optimistic.set(capability, optimisticValue);
  render();
  try {
    await host.executeCommand({ commandName, args, slotId });
    setTimeout(() => {
      if (state.optimistic.get(capability) === optimisticValue) {
        state.optimistic.delete(capability);
        render();
      }
    }, 3500);
  } catch (error) {
    state.optimistic.delete(capability);
    state.error = error instanceof Error ? error.message : "The air conditioner did not respond.";
  } finally {
    state.pending = "";
    render();
  }
}

async function connect(bootstrap) {
  state.bootstrap = bootstrap;
  render();
  if (!state.ready) {
    await host.ready({ height: Math.max(220, root.scrollHeight) });
    state.ready = true;
  }
  const bindings = Array.isArray(bootstrap?.bindings) ? bootstrap.bindings : [];
  const scope = bindings.map((slot) => [slot.id, slot.binding?.configId, slot.binding?.deviceKey, slot.binding?.capabilityId].join(":")).join("|");
  if (scope === state.bindingScope && state.subscriptions.length) return;
  for (const unsubscribe of state.subscriptions.splice(0)) {
    try { await unsubscribe(); } catch { /* Host may already have released it. */ }
  }
  state.bindingScope = scope;
  state.values.clear();
  state.optimistic.clear();
  const subscriptionParams = stateSubscriptionParams(bindings);
  if (subscriptionParams.capabilityIds.length) {
    try {
      const unsubscribe = await host.subscribeState(subscriptionParams, (event) => {
        if (event?.kind === "error") {
          state.error = event.error?.message || "Live climate updates are temporarily unavailable.";
        } else {
          state.error = "";
          updateValues(event);
        }
        if (!state.editingTarget) render();
      });
      state.subscriptions.push(unsubscribe);
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Unable to load climate state.";
      render();
    }
  }
}

if (root && host) host.subscribe((bootstrap) => void connect(bootstrap));
