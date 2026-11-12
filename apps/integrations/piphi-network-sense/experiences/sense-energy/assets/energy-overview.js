const host = window.PiPhiWidgetHost;
const root = document.querySelector("#piphi-widget-root");

if (!host || !root) {
  throw new Error("PiPhi Widget Host is unavailable.");
}

root.innerHTML = `
  <main class="sense-overview" aria-label="Sense Energy Overview">
    <header class="sense-header">
      <div>
        <span class="eyebrow">Live energy</span>
        <h2>Home usage</h2>
      </div>
      <button class="connection" type="button" data-piphi-interaction-target="energy-card" aria-label="View Sense connection details" hidden>
        <span class="connection-dot" aria-hidden="true"></span>
        <span data-value="connected">Unavailable</span>
      </button>
    </header>

    <section class="live-panel" aria-label="Live household power">
      <button class="hero-reading" type="button" data-piphi-interaction-target="home-power" aria-label="View household power history">
        <span class="reading-label">Using now</span>
        <span class="hero-value"><strong data-value="home-power">—</strong><small data-unit="home-power">W</small></span>
      </button>
      <button class="solar-reading" type="button" data-piphi-interaction-target="solar-power" aria-label="View solar power history">
        <span class="sun-icon" aria-hidden="true">☀</span>
        <span class="solar-copy">
          <small>Solar now</small>
          <span class="solar-value"><strong data-value="solar-power">—</strong><em data-unit="solar-power">W</em></span>
        </span>
      </button>
    </section>

    <section class="today-panel" aria-label="Daily and background energy at a glance">
      <div class="today-readings">
        <button type="button" data-piphi-interaction-target="usage-today" aria-label="View daily usage history">
          <span>Used</span><strong data-value="usage-today">—</strong><small data-unit="usage-today">kWh</small>
        </button>
        <button type="button" data-piphi-interaction-target="production-today" aria-label="View daily production history">
          <span>Produced</span><strong data-value="production-today">—</strong><small data-unit="production-today">kWh</small>
        </button>
        <button type="button" data-piphi-interaction-target="energy-card" aria-label="View background energy details">
          <span>Background</span><strong data-value="background-total">—</strong><small>W</small>
        </button>
      </div>
    </section>

    <p class="data-status" role="status" aria-live="polite">Loading Sense readings…</p>
  </main>`;

const values = new Map();
const slotIds = ["connected", "home-power", "solar-power", "usage-today", "production-today", "always-on", "other"];
const { bindings = [] } = await host.getBindings();
const capabilityToSlot = new Map(bindings
  .filter((slot) => slotIds.includes(slot.id) && slot.binding?.capabilityId)
  .map((slot) => [slot.binding.capabilityId, slot.id]));
let stopLive;

function numericValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, maximumFractionDigits = 1) {
  const number = numericValue(value);
  return number === null ? "—" : new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(number);
}

function applyState(slotId, state) {
  if (!state) return false;
  values.set(slotId, state);
  render();
  root.querySelector(".data-status").hidden = true;
  return true;
}

function render() {
  for (const slotId of slotIds) {
    const state = values.get(slotId);
    const valueNode = root.querySelector(`[data-value="${slotId}"]`);
    if (!valueNode || !state) continue;
    if (slotId === "connected") {
      const connected = state.value === true || state.value === 1 || ["true", "on", "online", "connected"].includes(String(state.value).toLowerCase());
      valueNode.textContent = connected ? "Connected" : "Unavailable";
      const connection = root.querySelector(".connection");
      connection.hidden = connected;
      connection.classList.toggle("has-attention", !connected);
      continue;
    }
    valueNode.textContent = formatNumber(state.value, slotId.includes("today") ? 1 : 0);
    const unitNode = root.querySelector(`[data-unit="${slotId}"]`);
    if (unitNode && state.unit) unitNode.textContent = state.unit;
  }

  const alwaysOn = numericValue(values.get("always-on")?.value) ?? 0;
  const other = numericValue(values.get("other")?.value) ?? 0;
  const home = numericValue(values.get("home-power")?.value) ?? 0;
  const backgroundTotal = alwaysOn + other;
  const alwaysPercent = backgroundTotal > 0 ? (alwaysOn / backgroundTotal) * 100 : 50;
  const backgroundPercent = home > 0 ? Math.min(100, (backgroundTotal / home) * 100) : 0;

  root.querySelector('[data-value="background-total"]').textContent = formatNumber(backgroundTotal, 0);
  root.querySelector('[data-value="background-total"]').title = `${formatNumber(backgroundPercent, 0)}% of live use · ${formatNumber(alwaysPercent, 0)}% always on`;
}

async function subscribeReadings() {
  const capabilityIds = bindings
    .filter((slot) => slotIds.includes(slot.id) && slot.binding?.capabilityId)
    .map((slot) => slot.binding.capabilityId);
  if (!capabilityIds.length) return;
  try {
    stopLive = await host.subscribeState({ capabilityIds }, (event) => {
      if (event?.kind === "point") {
        const slotId = capabilityToSlot.get(event.data?.capabilityId);
        if (slotId) applyState(slotId, { value: event.data?.value, unit: event.data?.unit });
      } else if (event?.kind === "snapshot") {
        for (const state of event.data?.states ?? []) {
          const slotId = capabilityToSlot.get(state.capability_id);
          if (slotId) applyState(slotId, { value: state.value ?? state.display_value, unit: state.unit });
        }
      } else if (event?.kind === "error") {
        const status = root.querySelector(".data-status");
        status.hidden = false;
        status.textContent = "Some Sense readings are unavailable";
      }
    });
  } catch (error) {
    console.warn("Sense readings subscription unavailable", error);
    const status = root.querySelector(".data-status");
    status.hidden = false;
    status.textContent = "Sense readings are temporarily unavailable";
  }
}

if (!capabilityToSlot.size) {
  const status = root.querySelector(".data-status");
  status.hidden = false;
  status.textContent = "Choose a Sense monitor in card settings";
}
await subscribeReadings();

let resizeFrame = 0;
const minimumGlanceHeight = 168;
function measuredContentHeight() {
  return Math.max(
    minimumGlanceHeight,
    Math.ceil(root.querySelector(".sense-overview").scrollHeight),
  );
}
function reportContentHeight() {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    void host.setHeight(measuredContentHeight()).catch(() => undefined);
  });
}
const resizeObserver = new ResizeObserver(reportContentHeight);
resizeObserver.observe(root.querySelector(".sense-overview"));
await host.ready({ height: measuredContentHeight() });

window.addEventListener("pagehide", () => {
  cancelAnimationFrame(resizeFrame);
  resizeObserver.disconnect();
  if (stopLive) void stopLive();
}, { once: true });
