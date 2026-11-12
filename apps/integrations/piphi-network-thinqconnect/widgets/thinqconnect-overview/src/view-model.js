const LIFECYCLE = new Set(["loading", "connecting", "empty", "live", "stale", "offline", "reconnecting", "denied", "error"]);

export function normalizeLifecycle(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (["snapshot", "point", "open", "online", "ready", "connected"].includes(normalized)) return "live";
  return LIFECYCLE.has(normalized) ? normalized : "error";
}

export function lifecycleCopy(value) {
  const lifecycle = normalizeLifecycle(value);
  if (lifecycle === "live") return "";
  if (["loading", "connecting", "reconnecting"].includes(lifecycle)) return "Updating appliance…";
  if (lifecycle === "empty") return "No compatible readings from this appliance";
  if (lifecycle === "stale") return "Last update may be delayed";
  if (lifecycle === "offline") return "Appliance is offline";
  if (lifecycle === "denied") return "Reconnect LG ThinQ to view readings";
  return "Unable to update appliance";
}

function camelCase(value) {
  return value.replace(/_([a-z0-9])/g, (_match, character) => character.toUpperCase());
}

function cleanValue(value) {
  if (typeof value === "string") return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 120);
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return value;
  return null;
}

export function projectState(data, capabilityIds) {
  const source = data?.primaryState || data?.state || data?.value || data || {};
  const output = {};
  if ((typeof source !== "object" || source === null) && capabilityIds.length === 1) {
    output[capabilityIds[0]] = cleanValue(source);
  }
  if (Array.isArray(data?.states)) {
    for (const item of data.states) {
      const capabilityId = item?.capability_id || item?.capabilityId;
      if (capabilityId) output[capabilityId] = cleanValue(item.value);
    }
  }
  const primaryCapabilityId = data?.primaryState?.capability_id || data?.primaryState?.capabilityId;
  if (primaryCapabilityId) output[primaryCapabilityId] = cleanValue(data.primaryState.value);
  if (data?.capabilityId) output[data.capabilityId] = cleanValue(data.value);
  for (const capabilityId of capabilityIds) {
    const value = source[capabilityId] ?? source[camelCase(capabilityId)];
    if (output[capabilityId] === undefined) output[capabilityId] = cleanValue(value);
  }
  return output;
}

export function formatMetric(value, unit = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    const formatted = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
    return unit ? `${formatted} ${unit}` : formatted;
  }
  const display = /^[A-Z0-9_ -]+$/.test(String(value))
    ? String(value).toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase())
    : String(value);
  return unit ? `${display} ${unit}` : display;
}
