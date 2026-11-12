import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { createRecoverySession, resolveStatus } from "./state.js";

const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const translationFallbacks = {
  "widget.title": "Devices & security", "widget.waiting": "Waiting for device data",
  "widget.region": "Device and security summary", "metric.online": "Devices online",
  "metric.known": "Known devices", "metric.certificates": "Certificates expiring",
  "metric.events": "Recent security events", "status.updating": "Updating device list…",
  "status.stale": "Last known values · update delayed", "status.offline": "Router is offline",
  "status.error": "Unable to update device list", "action.retry": "Retry", "action.retrying": "Retrying…",
};
const [context, settings, translatedEntries] = await Promise.all([
  host.getContext(), host.getSettings(),
  Promise.all(Object.entries(translationFallbacks).map(async ([key, fallback]) => {
    const value = await host.translate(key); return [key, value === key ? fallback : value];
  })),
]);
const copy = Object.fromEntries(translatedEntries);

root.innerHTML = `<style>
  :root{color-scheme:only light;font:var(--piphi-widget-font-size,14px)/var(--piphi-widget-line-height,1.4) var(--piphi-widget-font-family,system-ui,sans-serif);--pfsense-label-size:var(--piphi-widget-font-size-label,.75rem);--pfsense-value-size:var(--piphi-widget-font-size-value,1.125rem)}*{box-sizing:border-box}html,body{margin:0;background:transparent}main{padding:10px;color:var(--piphi-widget-text,CanvasText);background:transparent}
  h2{font-size:1rem;margin:0 0 8px}.stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:minmax(52px,auto);border-top:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 14%,transparent))}.stat{min-height:52px;min-width:0;display:flex;flex-direction:column;justify-content:center;padding:6px 8px;background:transparent}.stat:nth-child(even){border-inline-start:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 14%,transparent))}.stat:nth-child(n+3){border-top:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 14%,transparent))}
  small,[role=status]{color:var(--piphi-widget-text-muted,currentColor)}small{display:block;font-size:var(--pfsense-label-size);line-height:1.2}.value{display:block;margin-top:1px;font-size:var(--pfsense-value-size);line-height:1.15;font-weight:750;font-variant-numeric:tabular-nums}.alert{color:var(--piphi-widget-danger,#cc4b37)}.status-row{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:6px}.status-row[hidden]{display:none}[role=status]{margin:0;font-size:var(--pfsense-label-size)}.retry{min-width:44px;min-height:44px;padding:0 12px;border:0;border-radius:10px;background:color-mix(in srgb,var(--piphi-widget-accent,#2563eb) 12%,transparent);color:var(--piphi-widget-accent,#2563eb);font:inherit;font-size:var(--pfsense-label-size);font-weight:750;cursor:pointer}.retry[hidden]{display:none}.retry:disabled{cursor:progress;opacity:.72}.retry:focus-visible,h2:focus-visible{outline:3px solid var(--piphi-widget-accent,#2563eb);outline-offset:2px}main[data-stale="true"] .value{opacity:.62}main[data-stale="true"] .stats{background:color-mix(in srgb,var(--piphi-widget-warning,#b45309) 4%,transparent)}
  @media(max-width:300px){main{padding:8px}}@media(max-width:180px){.stats{grid-template-columns:1fr}.stat{flex-direction:row;justify-content:space-between;align-items:center;border-inline-start:0!important}.stat+ .stat{border-top:1px solid var(--piphi-widget-border,color-mix(in srgb,currentColor 14%,transparent))}.value{margin:0}.status-row{align-items:stretch;flex-direction:column}.retry{width:100%}}@media(prefers-reduced-motion:reduce){*{transition:none!important}}@media(forced-colors:active){.stats,.stat{border-color:CanvasText}.retry{border:1px solid ButtonText;background:ButtonFace;color:ButtonText}.retry:focus-visible,h2:focus-visible{outline-color:Highlight}}
</style><main data-state="loading" dir="${context.localization?.direction || "ltr"}"><h2 tabindex="-1">${escapeHtml(settings.title || copy["widget.title"])}</h2><section class="stats" aria-label="${escapeHtml(copy["widget.region"])}"><div class="stat"><small>${escapeHtml(copy["metric.online"])}</small><strong class="value" data-key="clients_online">—</strong></div><div class="stat"><small>${escapeHtml(copy["metric.known"])}</small><strong class="value" data-key="client_count">—</strong></div><div class="stat"><small>${escapeHtml(copy["metric.certificates"])}</small><strong class="value alert" data-certificates>—</strong></div><div class="stat"><small>${escapeHtml(copy["metric.events"])}</small><strong class="value" data-key="security_log_count">—</strong></div></section><div class="status-row" data-status-row><p role="status">${escapeHtml(copy["widget.waiting"])}</p><button class="retry" type="button" data-retry hidden>${escapeHtml(copy["action.retry"])}</button></div></main>`;

const status = root.querySelector("[role=status]");
const card = root.querySelector("main");
const statusRow = root.querySelector("[data-status-row]");
const retryButton = root.querySelector("[data-retry]");
const heading = root.querySelector("h2");
const capabilities = ["client_count", "clients_online", "certificates_expiring", "certificates_expired", "security_log_count", "ha_enabled", "clients"];
const state = {};
let hasLastKnownValues = false;
let restoreRetryFocus = false;
function renderStatus(model) {
  status.textContent = model.message; statusRow.hidden = model.phase === "live";
  retryButton.hidden = !model.retry; card.dataset.state = model.phase; card.dataset.stale = String(model.stale);
}
function renderState(data) {
  mergeState(state, data);
  hasLastKnownValues = Object.keys(state).length > 0;
  for (const node of root.querySelectorAll("[data-key]")) { const value = state[node.dataset.key]; if (value !== undefined && value !== null) node.textContent = formatNumber(value); }
  root.querySelector("[data-certificates]").textContent = formatNumber(Number(state.certificates_expiring || 0) + Number(state.certificates_expired || 0));
}
let resizeFrame = 0;
function reportContentHeight() {
  cancelAnimationFrame(resizeFrame);
  resizeFrame = requestAnimationFrame(() => {
    void host.setHeight(Math.ceil(card.scrollHeight)).catch(() => undefined);
  });
}
const resizeObserver = new ResizeObserver(reportContentHeight);
resizeObserver.observe(card);
await host.ready({ height: Math.ceil(card.scrollHeight) });
const selectedCapabilities = (context.bindings || [])
  .map((slot) => slot.binding?.capabilityId)
  .filter((capabilityId) => capabilities.includes(capabilityId));
const statusCopy = { updating: copy["status.updating"], stale: copy["status.stale"], offline: copy["status.offline"], error: copy["status.error"], waiting: copy["widget.waiting"] };
const recovery = createRecoverySession({
  read: () => host.getCapabilityState({ capabilityIds: selectedCapabilities, forceRefresh: true }),
  subscribe: (callback) => host.subscribeState({ capabilityIds: selectedCapabilities }, callback),
  onStart: () => { restoreRetryFocus = false; retryButton.disabled = true; retryButton.textContent = copy["action.retrying"]; card.setAttribute("aria-busy", "true"); },
  onRead: (data) => renderState(data),
  onRecovered: (_data, { restoreFocus = false }) => {
    renderStatus(resolveStatus({ kind: "snapshot" }, statusCopy, hasLastKnownValues));
    if (restoreFocus) heading.focus();
  },
  onEvent: (event) => {
    const model = resolveStatus(event, statusCopy, hasLastKnownValues);
    if (event.kind === "snapshot" || event.kind === "point") renderState(event.data);
    renderStatus(model); reportContentHeight();
  },
  onError: (_error, { restoreFocus = false }) => {
    renderStatus(resolveStatus({ kind: "error" }, statusCopy, hasLastKnownValues));
    restoreRetryFocus = restoreFocus;
  },
  onSettled: () => { retryButton.disabled = false; retryButton.textContent = copy["action.retry"]; card.removeAttribute("aria-busy"); if (restoreRetryFocus) retryButton.focus(); reportContentHeight(); },
});
retryButton.addEventListener("click", () => { void recovery.recover({ restoreFocus: true }); });
await recovery.recover();
window.addEventListener("pagehide", () => { cancelAnimationFrame(resizeFrame); resizeObserver.disconnect(); void recovery.stop(); }, { once: true });
function mergeState(target, data) {
  if (Array.isArray(data?.states)) for (const item of data.states) {
    const capabilityId = item?.capability_id || item?.capabilityId;
    if (capabilityId) target[capabilityId] = item.value;
  }
  if (data?.primaryState?.capability_id) target[data.primaryState.capability_id] = data.primaryState.value;
  if (data?.capabilityId) target[data.capabilityId] = data.value;
  const legacy = data?.state || (data?.primaryState?.capability_id ? null : data?.primaryState);
  if (legacy && typeof legacy === "object") Object.assign(target, legacy);
}
function formatNumber(value) { const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat(context.localization?.locale).format(number) : "—"; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }
