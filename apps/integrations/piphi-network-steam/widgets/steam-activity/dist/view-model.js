const LIFECYCLE = new Set(["loading", "empty", "live", "stale", "offline", "reconnecting", "denied", "error"]);

export function normalizeLifecycle(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "snapshot" || normalized === "point") return "live";
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
  return Object.fromEntries(capabilityIds.map((id) => [id, cleanValue(source[id] ?? source[camelCase(id)])]));
}

export function formatMinutes(value) {
  if (!Number.isFinite(value)) return "—";
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}
