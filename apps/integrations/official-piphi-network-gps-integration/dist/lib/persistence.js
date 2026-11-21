import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
const DEFAULT_CONFIG_PATH = "/var/lib/piphi/gps-configs.json";
function configPath() {
    return process.env.PIPHI_GPS_CONFIG_PATH || DEFAULT_CONFIG_PATH;
}
export async function loadPersistedConfigs() {
    try {
        const payload = JSON.parse(await readFile(configPath(), "utf8"));
        if (!Array.isArray(payload))
            return [];
        return payload.filter((item) => Boolean(item && typeof item === "object" && typeof item.path === "string"));
    }
    catch (error) {
        const code = error.code;
        if (code === "ENOENT" || error instanceof SyntaxError)
            return [];
        throw error;
    }
}
export async function persistConfigs(configs) {
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
