export function createSenseStateReducer() {
  const values = {};
  let meta = {};

  return {
    apply(event = {}) {
      if (event.kind === "snapshot") {
        const data = event.data || {};
        for (const state of Array.isArray(data.states) ? data.states : []) {
          const capabilityId = String(state?.capability_id || state?.capabilityId || "").trim();
          if (capabilityId) values[capabilityId] = state.value;
        }
        const primary = data.primaryState;
        const primaryId = String(primary?.capability_id || primary?.capabilityId || data.primaryCapabilityId || "").trim();
        if (primaryId && primary && "value" in primary && values[primaryId] === undefined) {
          values[primaryId] = primary.value;
        }
        meta = {
          configId: String(data.configId || data.binding?.configId || ""),
          sourceLabel: String(data.binding?.deviceLabel || data.binding?.sourceLabel || data.binding?.deviceKey || ""),
          provenanceLabel: String(data.primarySourceLabel || ""),
        };
      } else if (event.kind === "point") {
        const data = event.data || {};
        const capabilityId = String(data.capabilityId || data.capability_id || "").trim();
        if (capabilityId) values[capabilityId] = data.value;
      }
      return { values: { ...values }, meta: { ...meta } };
    },
  };
}

export function describeSenseStreamEvent(event = {}) {
  if (event.kind === "snapshot" || event.kind === "point") return { hidden: true, message: "" };
  if (event.kind === "status") {
    const status = String(event.status || "").toLowerCase();
    if (status === "open" || status === "connecting") return { hidden: true, message: "" };
    if (status === "reconnecting") return { hidden: false, message: "Reconnecting to Sense…" };
    if (status === "closed") return { hidden: false, message: "Sense data is unavailable." };
    return { hidden: true, message: "" };
  }
  if (event.kind === "error") {
    return { hidden: false, message: "Sense data is unavailable." };
  }
  return { hidden: true, message: "" };
}
