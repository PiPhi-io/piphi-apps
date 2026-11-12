const LIFECYCLE = new Set(["loading", "empty", "live", "stale", "offline", "reconnecting", "denied", "error"]);

export function normalizeLifecycle(value) {
  const state = String(value || "").trim().toLowerCase();
  if (state === "snapshot" || state === "point") return "live";
  if (state === "open") return "live";
  if (state === "connecting" || state === "closed") return "reconnecting";
  return LIFECYCLE.has(state) ? state : "error";
}

export function projectState(data) {
  const source = data?.primaryState || data?.state || data?.value || data || {};
  const values = {};
  if (Array.isArray(data?.states)) {
    for (const item of data.states) {
      const capabilityId = item?.capability_id || item?.capabilityId;
      if (capabilityId) values[capabilityId] = item.value;
    }
  }
  const primaryCapabilityId = data?.primaryState?.capability_id || data?.primaryState?.capabilityId;
  if (primaryCapabilityId) values[primaryCapabilityId] = data.primaryState.value;
  if (data?.capabilityId) values[data.capabilityId] = data.value;
  const value = (capabilityId) => values[capabilityId] ?? source?.[capabilityId];
  const number = (value, min, max) => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max ? value : null;
  const printStatus = value("print_status");
  const status = typeof printStatus === "string" && /^[A-Za-z0-9_ -]{1,32}$/.test(printStatus) ? printStatus : "";
  return {
    connected: value("connected") === true,
    simulation_mode: value("simulation_mode") === true,
    print_status: status,
    print_progress_percent: number(value("print_progress_percent"), 0, 100),
    remaining_time_minutes: number(value("remaining_time_minutes"), 0, 10080),
    current_layer: number(value("current_layer"), 0, 100000),
    total_layers: number(value("total_layers"), 0, 100000),
    nozzle_temperature_c: number(value("nozzle_temperature_c"), -40, 500),
    bed_temperature_c: number(value("bed_temperature_c"), -40, 200),
  };
}

export function formatStatus(value) {
  if (!value) return "Waiting for printer";
  return value.replaceAll("_", " ").toLowerCase().replace(/^./, (first) => first.toUpperCase());
}
