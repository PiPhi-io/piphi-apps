import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type { ActiveConfig } from "./runtime.js";

const DEFAULT_CONFIG_PATH = "/var/lib/piphi/gps-configs.json";

function configPath(): string {
  return process.env.PIPHI_GPS_CONFIG_PATH || DEFAULT_CONFIG_PATH;
}

export async function loadPersistedConfigs(): Promise<ActiveConfig[]> {
  try {
    const payload = JSON.parse(await readFile(configPath(), "utf8")) as unknown;
    if (!Array.isArray(payload)) return [];
    return payload.filter(
      (item): item is ActiveConfig =>
        Boolean(item && typeof item === "object" && typeof item.path === "string"),
    );
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT" || error instanceof SyntaxError) return [];
    throw error;
  }
}

export async function persistConfigs(configs: ActiveConfig[]): Promise<void> {
  const path = configPath();
  const temporary = `${path}.tmp`;
  const safeConfigs = configs.map(({ configId, deviceId, integrationId, path, containerId, configName }) => ({
    configId,
    deviceId,
    integrationId,
    path,
    containerId,
    configName,
  }));
  await mkdir(dirname(path), { recursive: true });
  await writeFile(temporary, `${JSON.stringify(safeConfigs, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path);
}
