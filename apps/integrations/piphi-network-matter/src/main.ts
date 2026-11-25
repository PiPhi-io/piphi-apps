import { fileURLToPath } from "node:url";
import { createApp } from "./app.js";
import { ConfigStore } from "./config-store.js";
import { CoreClient } from "./core-client.js";
import { Reconciler } from "./reconciler.js";
import { settingsFromEnv } from "./settings.js";
import { SidecarClient } from "./sidecar-client.js";

export function buildRuntime() {
  const settings = settingsFromEnv();
  const sidecar = new SidecarClient(settings.sidecarUrl, settings.sidecarToken);
  const configs = new ConfigStore(settings.configPath);
  const core = new CoreClient({
    ...(settings.telemetryEndpoint ? { endpoint: settings.telemetryEndpoint } : {}),
    ...(settings.eventEndpoint ? { eventEndpoint: settings.eventEndpoint } : {}),
    ...(settings.coreContainerId ? { containerId: settings.coreContainerId } : {}),
    ...(settings.coreToken ? { token: settings.coreToken } : {}),
    ...(settings.coreConfigId ? { configId: settings.coreConfigId } : {}),
  });
  const reconciler = new Reconciler(sidecar, configs, core, settings.reconcileIntervalMs);
  return createApp(reconciler, sidecar, configs, { allowMutations: settings.allowMutations });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const app = buildRuntime();
  await app.listen({ host: "0.0.0.0", port: Number(process.env.PORT ?? 4221) });
}
