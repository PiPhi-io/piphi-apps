const LIFECYCLE = new Set(["loading", "empty", "live", "stale", "offline", "reconnecting", "denied", "error"]);

export function normalizeLifecycle(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "snapshot" || normalized === "point") return "live";
  if (normalized === "open") return "live";
  if (normalized === "connecting" || normalized === "closed") return "reconnecting";
  return LIFECYCLE.has(normalized) ? normalized : "error";
}

function camelCase(value) {
  return value.replace(/_([a-z0-9])/g, (_match, character) => character.toUpperCase());
}

function cleanValue(value) {
  if (typeof value === "string") return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160);
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "boolean") return value;
  return null;
}

export function projectState(data, capabilityIds) {
  const source = data?.primaryState || data?.state || data?.value || data || {};
  const output = {};
  if (Array.isArray(data?.states)) {
    for (const item of data.states) {
      const capabilityId = item?.capability_id || item?.capabilityId;
      if (capabilityId) output[capabilityId] = cleanValue(item.value);
    }
  }
  const primaryCapabilityId = data?.primaryState?.capability_id || data?.primaryState?.capabilityId;
  if (primaryCapabilityId) output[primaryCapabilityId] = cleanValue(data.primaryState.value);
  if (data?.capabilityId) output[data.capabilityId] = cleanValue(data.value);
  for (const id of capabilityIds) {
    if (output[id] === undefined) output[id] = cleanValue(source?.[id] ?? source?.[camelCase(id)]);
  }
  return output;
}

export function formatMinutes(value) {
  if (!Number.isFinite(value)) return "—";
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}
