// Vendored from piphi-network-widget-sdk/src/optimistic-control.ts.
// Keep this self-contained module in the signed Kasa artifact for sandboxed imports.
function readingTime(raw) {
    if (raw == null || raw === "") return null;
    const parsed = typeof raw === "number" ? raw : /^\d+$/.test(raw) ? Number(raw) : Date.parse(raw);
    if (!Number.isFinite(parsed)) return null;
    return parsed < 1e12 ? parsed * 1000 : parsed;
}

/** Command acceptance is not device confirmation; observe a later reading to reconcile. */
export function createOptimisticControl(options = {}) {
    let confirmed = options.initial;
    let override = null;
    let lastReadingAt = 0;
    let confirmationTimer = null;
    const now = options.now ?? Date.now;
    const equals = options.equals ?? Object.is;
    const confirmationMs = Math.max(1, options.confirmationMs ?? 10_000);
    const visible = () => override?.value ?? confirmed;
    const notify = () => options.onChange?.(visible());
    const clearTimer = () => {
        if (confirmationTimer) clearTimeout(confirmationTimer);
        confirmationTimer = null;
    };
    return {
        get value() { return visible(); },
        get confirmed() { return confirmed; },
        get pending() { return override?.pending ?? false; },
        get awaitingConfirmation() { return override !== null && !override.pending; },
        begin(next) {
            clearTimer();
            override = { value: next, issuedAt: now(), pending: true };
            notify();
        },
        accept() {
            if (!override) return;
            override.pending = false;
            const accepted = override;
            clearTimer();
            confirmationTimer = setTimeout(() => {
                if (override !== accepted) return;
                override = null;
                confirmationTimer = null;
                notify();
            }, confirmationMs);
            notify();
        },
        reject() {
            clearTimer();
            override = null;
            notify();
        },
        observe(value, observedAt) {
            const timestamp = readingTime(observedAt);
            if (timestamp !== null && timestamp < lastReadingAt) return;
            if (timestamp === null && lastReadingAt > 0 && (!override || !equals(value, override.value))) return;
            if (timestamp !== null) lastReadingAt = timestamp;
            confirmed = value;
            if (override && (equals(value, override.value)
                || (!override.pending && timestamp !== null && timestamp >= override.issuedAt))) {
                override = null;
                clearTimer();
            }
            notify();
        },
        reset(value) {
            clearTimer();
            confirmed = value;
            override = null;
            lastReadingAt = 0;
            notify();
        },
        destroy() {
            clearTimer();
            override = null;
        },
    };
}
