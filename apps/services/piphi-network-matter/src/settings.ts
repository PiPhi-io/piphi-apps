import { resolve } from "node:path";

export const integrationId = "piphi.service.matter-sidecar";
export const integrationName = "Matter Sidecar";
export const integrationVersion = "0.2.0-alpha.3";

export interface MatterSettings {
  apiHost: string;
  apiPort: number;
  backendHost: string;
  backendPort: number;
  backendUrl: string;
  storageDir: string;
  manageBackend: boolean;
  enableBle: boolean;
  primaryInterface?: string;
}

function port(value: string | undefined, fallback: number): number {
  const parsed = Number(value ?? fallback);
  return Number.isInteger(parsed) && parsed > 0 && parsed <= 65535 ? parsed : fallback;
}

function runtimePort(env: NodeJS.ProcessEnv, fallback: number): number {
  if (env.PORT === undefined) return port(env.MATTER_API_PORT, fallback);
  const parsed = Number(env.PORT);
  if (!/^\d+$/.test(env.PORT) || !Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new RangeError("PORT must be an integer between 1 and 65535.");
  }
  return parsed;
}

function enabled(value: string | undefined, fallback = false): boolean {
  if (value === undefined) return fallback;
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export function loadSettings(env: NodeJS.ProcessEnv = process.env): MatterSettings {
  const backendHost = env.MATTER_BACKEND_HOST ?? "127.0.0.1";
  const backendPort = port(env.MATTER_BACKEND_PORT, 5580);
  const primaryInterface = env.MATTER_PRIMARY_INTERFACE?.trim() || undefined;
  return {
    apiHost: env.MATTER_API_HOST ?? "127.0.0.1",
    apiPort: runtimePort(env, 8710),
    backendHost,
    backendPort,
    backendUrl: env.MATTER_BACKEND_URL ?? `ws://${backendHost}:${backendPort}/ws`,
    storageDir: resolve(env.MATTER_STORAGE_DIR ?? "/var/lib/piphi/matter"),
    manageBackend: enabled(env.MATTER_MANAGE_BACKEND, true),
    enableBle: enabled(env.MATTER_ENABLE_BLE),
    ...(primaryInterface === undefined ? {} : { primaryInterface }),
  };
}
