export function resolveConnectionAttention(value, offlineLabel = "Offline") {
  const normalized = String(value ?? "").toLowerCase();
  const connected = value === true
    || value === 1
    || ["1", "true", "connected", "online", "open", "up"].includes(normalized);
  return {
    connected,
    hidden: connected,
    label: connected ? "" : offlineLabel,
  };
}

export function resolveStatus(event, copy, hasLastKnownValues = false) {
  const value = String(event?.status || event?.kind || "").trim().toLowerCase();
  if (["snapshot", "point", "open", "online", "ready", "connected", "live"].includes(value)) {
    return { phase: "live", message: "", stale: false, retry: false };
  }
  if (["loading", "connecting", "reconnecting"].includes(value)) {
    return { phase: "loading", message: copy.updating, stale: hasLastKnownValues, retry: false };
  }
  if (value === "stale") {
    return { phase: "stale", message: copy.stale, stale: true, retry: true };
  }
  if (value === "offline") {
    return { phase: "offline", message: copy.offline, stale: hasLastKnownValues, retry: true };
  }
  if (["error", "closed", "denied"].includes(value)) {
    return { phase: "error", message: copy.error, stale: hasLastKnownValues, retry: true };
  }
  return { phase: "waiting", message: copy.waiting, stale: hasLastKnownValues, retry: false };
}

export function statusText(event, copy = {
  updating: "Updating router status…",
  stale: "Last known values · update delayed",
  offline: "Router is offline",
  error: "Unable to update router status",
  waiting: "Waiting for router data",
}) {
  return resolveStatus(event, copy).message;
}

export function createRecoverySession({ read, subscribe, onStart, onRead, onRecovered, onEvent, onError, onSettled }) {
  let activeRequest = null;
  let unsubscribe = null;
  function handleEvent(event) {
    const phase = String(event?.status || event?.kind || "").trim().toLowerCase();
    if (["error", "closed", "denied"].includes(phase) && unsubscribe) {
      const stop = unsubscribe;
      unsubscribe = null;
      void Promise.resolve(stop()).catch(() => undefined);
    }
    onEvent?.(event);
  }
  function recover(context = {}) {
    if (activeRequest) return activeRequest;
    onStart?.(context);
    activeRequest = Promise.resolve()
      .then(read)
      .then(async (data) => {
        onRead?.(data, context);
        if (!unsubscribe) unsubscribe = await subscribe(handleEvent);
        onRecovered?.(data, context);
      })
      .catch((error) => onError?.(error, context))
      .finally(() => {
        onSettled?.(context);
        activeRequest = null;
      });
    return activeRequest;
  }
  async function stop() {
    const stopSubscription = unsubscribe;
    unsubscribe = null;
    if (stopSubscription) await stopSubscription();
  }
  return { recover, stop, hasSubscription: () => Boolean(unsubscribe) };
}
