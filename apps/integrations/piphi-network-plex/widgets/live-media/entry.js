import { getInjectedPiPhiWidgetHost } from "piphi-network-widget-sdk";
import { mountLiveMediaWidget } from "./widget.js";

const cleanup = await mountLiveMediaWidget(
  getInjectedPiPhiWidgetHost(),
  document.querySelector("#piphi-widget-root") || document.body,
);
window.addEventListener("pagehide", cleanup, { once: true });
