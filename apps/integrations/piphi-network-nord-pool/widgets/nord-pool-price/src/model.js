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
  const value = (capabilityId, camelId) => values[capabilityId] ?? source?.[capabilityId] ?? source?.[camelId];
  const numeric = (value) => typeof value === "number" && Number.isFinite(value) ? value : null;
  const plainText = (value) => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 32) : "";
  return {
    connected: value("connected", "connected") === true,
    market_area: plainText(value("market_area", "marketArea")),
    current_price_per_kwh: numeric(value("current_price_per_kwh", "currentPricePerKwh")),
    next_price_per_kwh: numeric(value("next_price_per_kwh", "nextPricePerKwh")),
    price_unit: plainText(value("price_unit", "priceUnit")),
  };
}

export function formatPrice(value, locale = "en") {
  return value === null ? "—" : new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 3 }).format(value);
}
