import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { createSenseStateReducer, describeSenseStreamEvent } from "./state.js";
import { applyApplianceView, createApplianceView } from "./view.js";

const host = getInjectedPiPhiWidgetHost();
const root = document.querySelector("#piphi-widget-root") || document.body;
const context = await host.getContext();
const title = await host.translate("widget.title");

root.innerHTML = `
  <style>
    :root { color-scheme:light dark; font:var(--piphi-widget-font-size,14px)/1.4 var(--piphi-widget-font-family,system-ui,sans-serif); }
    * { box-sizing:border-box; }
    main { min-height:0; padding:4px; color:var(--piphi-widget-text,#0f172a); background:transparent; overflow:hidden; }
    header { display:flex; align-items:start; justify-content:space-between; gap:12px; }
    h2 { margin:0; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:1rem; line-height:1.25; }
    .state { color:var(--piphi-widget-text-muted,#52647a); font-size:12px; white-space:nowrap; }
    .metrics { display:grid; grid-template-columns:minmax(0,1.35fr) minmax(0,1fr); margin-top:10px; border-top:1px solid var(--piphi-widget-border,#d7dee8); }
    .metric { min-height:54px; padding:9px 4px 4px; }
    .metric + .metric { padding-inline-start:12px; border-inline-start:1px solid var(--piphi-widget-border,#d7dee8); }
    .label { display:block; color:var(--piphi-widget-text-muted,#52647a); font-size:12px; }
    .value { display:block; margin-top:2px; font-size:1.18rem; font-weight:760; font-variant-numeric:tabular-nums; }
    [role=status] { margin:7px 0 0; color:var(--piphi-widget-danger,#b91c1c); font-size:12px; }
    [role=status][hidden] { display:none; }
    @media (forced-colors:active) { .metrics,.metric + .metric { border-color:CanvasText; } }
  </style>
  <main dir="${context.localization?.direction || "ltr"}">
    <header><h2></h2><span class="state">Waiting</span></header>
    <section class="metrics" aria-label="Sense appliance energy">
      <div class="metric"><span class="label">Now</span><strong class="value power">—</strong></div>
      <div class="metric"><span class="label">Today</span><strong class="value energy">—</strong></div>
    </section>
    <p role="status" hidden></p>
  </main>`;

const nodes = {
  title: root.querySelector("h2"),
  state: root.querySelector(".state"),
  power: root.querySelector(".power"),
  energy: root.querySelector(".energy"),
};
const status = root.querySelector("[role=status]");
const stateReducer = createSenseStateReducer();
nodes.title.textContent = title;

const stop = await host.subscribeState({}, (event) => {
  const stream = describeSenseStreamEvent(event);
  status.hidden = stream.hidden;
  status.textContent = stream.message;
  const reduced = stateReducer.apply(event);
  if (event.kind === "snapshot" || event.kind === "point") {
    applyApplianceView(nodes, createApplianceView(reduced.values, reduced.meta));
  }
  host.setHeight(status.hidden ? 112 : 132);
});

window.addEventListener("pagehide", stop, { once:true });
await host.ready({ height:112 });
