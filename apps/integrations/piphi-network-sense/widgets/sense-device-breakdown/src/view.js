export function createApplianceView(values = {}, meta = {}) {
  const power = finiteNumber(values.device_power_w);
  const dailyEnergy = finiteNumber(values.device_daily_energy_kwh);
  const explicitState = values.device_on;
  const isOn = explicitState === true || explicitState === 1 || String(explicitState).toLowerCase() === "true";
  const hasState = explicitState !== undefined && explicitState !== null;
  return {
    title: String(meta.sourceLabel || "Sense appliance"),
    state: hasState ? (isOn ? "On" : "Off") : power == null ? "Waiting" : power > 0 ? "On" : "Off",
    power: power == null ? "—" : `${formatNumber(power)} W`,
    energy: dailyEnergy == null ? "—" : `${formatNumber(dailyEnergy)} kWh`,
  };
}

export function applyApplianceView(nodes, view) {
  if (nodes.title && view.title) nodes.title.textContent = view.title;
  nodes.state.textContent = view.state;
  nodes.power.textContent = view.power;
  nodes.energy.textContent = view.energy;
}

function finiteNumber(value) {
  if (value === "" || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits:1 }).format(value);
}
