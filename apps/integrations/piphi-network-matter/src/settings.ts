export interface Settings {
  sidecarUrl: string;
  sidecarToken: string;
  configPath: string;
  reconcileIntervalMs: number;
  telemetryEndpoint?: string;
  eventEndpoint?: string;
  coreContainerId?: string;
  coreToken?: string;
  coreConfigId?: string;
}

export function settingsFromEnv(env: NodeJS.ProcessEnv = process.env): Settings {
  const sidecarUrl = String(env.PIPHI_MATTER_SIDECAR_URL ?? "").replace(/\/$/, "");
  const sidecarToken = String(env.PIPHI_MATTER_SIDECAR_TOKEN ?? env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? "");
  if (!sidecarUrl) throw new Error("PIPHI_MATTER_SIDECAR_URL is required");
  if (!sidecarToken && env.NODE_ENV === "production") throw new Error("PIPHI_MATTER_SIDECAR_TOKEN is required in production");
  const interval = Number(env.PIPHI_MATTER_RECONCILE_INTERVAL_MS ?? 5000);
  return {
    sidecarUrl,
    sidecarToken,
    configPath: env.PIPHI_MATTER_CONFIG_PATH ?? "/app/data/config.json",
    reconcileIntervalMs: Number.isFinite(interval) && interval >= 250 ? interval : 5000,
    ...(env.PIPHI_TELEMETRY_ENDPOINT ? { telemetryEndpoint: env.PIPHI_TELEMETRY_ENDPOINT } : {}),
    ...(env.PIPHI_EVENTS_ENDPOINT ? { eventEndpoint: env.PIPHI_EVENTS_ENDPOINT } : {}),
    ...(env.PIPHI_CONTAINER_ID ? { coreContainerId: env.PIPHI_CONTAINER_ID } : {}),
    ...(env.PIPHI_INTEGRATION_INTERNAL_TOKEN ? { coreToken: env.PIPHI_INTEGRATION_INTERNAL_TOKEN } : {}),
    ...(env.PIPHI_CONFIG_ID ? { coreConfigId: env.PIPHI_CONFIG_ID } : {}),
  };
}
