import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { configureGPSDevice, deconfigureGPSDevice, getGPSerialPort, scoreGPSPort, setGPSTestHooksForTests, } from "../lib/gps.js";
import { loadPersistedConfigs } from "../lib/persistence.js";
import { getActiveConfigs, getRuntimeSnapshot, resetRuntimeForTests } from "../lib/runtime.js";
import { restoreRuntimeConfigs } from "../lib/startup.js";
class RecoveringSerial extends EventEmitter {
    isOpen = false;
    attempts = 0;
    pipe(destination) {
        return destination;
    }
    open(callback) {
        this.attempts += 1;
        if (this.attempts === 1) {
            callback(new Error("receiver unplugged"));
            return;
        }
        this.isOpen = true;
        callback(null);
    }
    close(callback) {
        this.isOpen = false;
        callback(null);
    }
}
const originalEnv = { ...process.env };
const temporaryDirectories = [];
test.afterEach(async () => {
    await deconfigureGPSDevice();
    setGPSTestHooksForTests(null);
    await Promise.all(temporaryDirectories.splice(0).map((path) => rm(path, { recursive: true, force: true })));
    process.env = { ...originalEnv };
    resetRuntimeForTests();
});
test("serial reconnect uses bounded retry and recovers after unplug", async () => {
    const directory = await mkdtemp(join(tmpdir(), "piphi-gps-recovery-"));
    temporaryDirectories.push(directory);
    const serial = new RecoveringSerial();
    process.env.PIPHI_GPS_CONFIG_PATH = join(directory, "configs.json");
    process.env.GPS_RECONNECT_BASE_MS = "10";
    process.env.GPS_RECONNECT_MAX_MS = "20";
    setGPSTestHooksForTests({ createSerialConnection: () => serial });
    await configureGPSDevice({ path: "/dev/ttyUSB-recovery", device_id: "receiver-recovery" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    const state = getRuntimeSnapshot();
    assert.equal(serial.attempts, 2);
    assert.equal(state.devices["receiver-recovery"]?.connected, true);
});
test("simulation mode produces deterministic hardware-independent fixes", async () => {
    const directory = await mkdtemp(join(tmpdir(), "piphi-gps-simulation-"));
    temporaryDirectories.push(directory);
    process.env.PIPHI_GPS_CONFIG_PATH = join(directory, "configs.json");
    process.env.GPS_SIMULATION_MODE = "true";
    process.env.GPS_FRESHNESS_INTERVAL_MS = "10";
    await configureGPSDevice({ path: "simulation://receiver-1", device_id: "synthetic-receiver" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    const state = getRuntimeSnapshot();
    assert.equal(state.devices["synthetic-receiver"]?.connected, true);
    assert.equal(state.devices["synthetic-receiver"]?.fix_details.signal_state, "fixed");
    const gps = await getGPSerialPort("simulation://receiver-1");
    assert.ok(gps?.fixState.lastGoodFix);
    gps.fixState.rmc = null;
    gps.fixState.gga = null;
    gps.fixState.gsa = null;
    gps.fixState.lastGoodFix.tsMs = Date.now() - 16_000;
    await new Promise((resolve) => setTimeout(resolve, 75));
    const staleState = getRuntimeSnapshot();
    assert.equal(staleState.devices["synthetic-receiver"]?.fix_details.signal_state, "stale");
    assert.equal(staleState.devices["synthetic-receiver"]?.fix_details.stale, true);
});
test("persisted configuration excludes secrets and restores after restart", async () => {
    const directory = await mkdtemp(join(tmpdir(), "piphi-gps-persistence-"));
    temporaryDirectories.push(directory);
    const path = join(directory, "configs.json");
    process.env.PIPHI_GPS_CONFIG_PATH = path;
    process.env.GPS_SIMULATION_MODE = "true";
    await writeFile(path, `${JSON.stringify([
        {
            configId: "persisted-config",
            deviceId: "persisted-receiver",
            integrationId: "official-usb-gps-integration",
            path: "simulation://persisted",
            containerId: "container-persisted",
            configName: "Persisted GPS",
        },
    ])}\n`);
    await restoreRuntimeConfigs();
    assert.equal(getActiveConfigs()[0]?.deviceId, "persisted-receiver");
    const persisted = await loadPersistedConfigs();
    assert.equal(persisted[0]?.path, "simulation://persisted");
    assert.equal((await readFile(path, "utf8")).includes("secret"), false);
});
test("stable receiver identity survives serial path changes", () => {
    const first = scoreGPSPort({
        path: "/dev/ttyUSB0",
        vendorId: "1546",
        productId: "01a7",
        serialNumber: "receiver-serial",
    });
    const second = scoreGPSPort({
        path: "/dev/ttyUSB7",
        vendorId: "1546",
        productId: "01a7",
        serialNumber: "receiver-serial",
    });
    assert.equal(first.id, second.id);
    assert.match(first.id, /^gps-[a-f0-9]{20}$/);
});
test("startup rehydrates managed runtime configuration from Core", async () => {
    const directory = await mkdtemp(join(tmpdir(), "piphi-gps-core-"));
    temporaryDirectories.push(directory);
    process.env.PIPHI_GPS_CONFIG_PATH = join(directory, "configs.json");
    process.env.GPS_SIMULATION_MODE = "true";
    process.env.PIPHI_CONTAINER_ID = "core-container";
    process.env.PIPHI_INTEGRATION_INTERNAL_TOKEN = "core-token";
    let receivedToken = "";
    const server = createServer((request, response) => {
        receivedToken = String(request.headers["x-piphi-integration-token"] ?? "");
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify([
            {
                config_data: {
                    id: "core-config",
                    config_id: "core-config",
                    device_id: "core-receiver",
                    path: "simulation://core",
                    container_id: "core-container",
                },
            },
        ]));
    });
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    process.env.PIPHI_CORE_BASE_URL = `http://127.0.0.1:${address.port}`;
    try {
        await restoreRuntimeConfigs();
        assert.equal(receivedToken, "core-token");
        assert.equal(getActiveConfigs()[0]?.deviceId, "core-receiver");
    }
    finally {
        await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    }
});
