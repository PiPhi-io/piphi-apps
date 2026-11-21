import { configureGPSDevice } from "./gps.js";
import { loadPersistedConfigs } from "./persistence.js";

interface CoreConfigRow {
  config_data?: Record<string, unknown>;
}

async function fetchCoreConfigs(): Promise<Record<string, unknown>[]> {
  const baseUrl = String(process.env.PIPHI_CORE_BASE_URL ?? "").replace(/\/$/, "");
  const containerId = String(process.env.PIPHI_CONTAINER_ID ?? "").trim();
  const token = String(process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN ?? "").trim();
  if (!baseUrl || !containerId || !token) return [];

  const url = new URL("/api/v2/integrations/config/fetch/all/by/container/internal", baseUrl);
  url.searchParams.set("container_id", containerId);
  const response = await fetch(url, {
    headers: {
      "X-Container-Id": containerId,
      "X-PiPhi-Integration-Token": token,
    },
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`Core config fetch failed with HTTP ${response.status}`);
  const rows = (await response.json()) as unknown;
  if (!Array.isArray(rows)) throw new Error("Core config response must be an array");
  return rows
    .map((row) => (row as CoreConfigRow).config_data)
    .filter((config): config is Record<string, unknown> => Boolean(config));
}

export async function restoreRuntimeConfigs(): Promise<void> {
  const local = await loadPersistedConfigs();
  for (const config of local) {
    if (!config.path) continue;
    await configureGPSDevice({
      id: config.configId,
      config_id: config.configId,
      device_id: config.deviceId,
      integration_id: config.integrationId,
      container_id: config.containerId,
      configName: config.configName,
      path: config.path,
    });
  }

  try {
    const coreConfigs = await fetchCoreConfigs();
    for (const config of coreConfigs) await configureGPSDevice(config);
  } catch {
    // The durable local snapshot is the offline startup fallback.
  }
}
