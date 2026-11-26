import { readFile, rename, statfs, writeFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { connectAsync } from "mqtt";

import { confineBrokerInputPaths, loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy, readPrincipalPassword } from "./identity.js";

const execFileAsync = promisify(execFile);

async function main(): Promise<void> {
  const config = await confineBrokerInputPaths(loadBrokerConfig());
  const policy = await loadIdentityPolicy(config);
  const health = policy.principals.find((principal) => principal.health);
  if (!health) throw new Error("Health principal is not configured");
  const password = await readPrincipalPassword(health, config);
  const host = process.env.MQTT_HEALTH_HOST?.trim() || "127.0.0.1";
  const protocol = config.tlsEnabled ? "mqtts" : "mqtt";
  const id = `${Date.now()}-${process.pid}`;
  const topic = `${config.topicPrefix}/_health/round-trip`;
  const client = await connectAsync(`${protocol}://${host}:${config.port}`, {
    protocolVersion: 5,
    username: health.username,
    password: password ?? undefined,
    clientId: health.username,
    clean: true,
    connectTimeout: 3_000,
    reconnectPeriod: 0,
    rejectUnauthorized: true,
    servername: process.env.MQTT_TLS_SERVER_NAME?.trim() || undefined,
    ca: config.tlsCaFile ? await readFile(config.tlsCaFile) : undefined,
    cert: config.tlsRequireClientCertificate && config.healthTlsCertFile ? await readFile(config.healthTlsCertFile) : undefined,
    key: config.tlsRequireClientCertificate && config.healthTlsKeyFile ? await readFile(config.healthTlsKeyFile) : undefined,
  });

  try {
    await client.subscribeAsync(topic, { qos: 1 });
    const received = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("MQTT lifecycle round trip timed out")), 3_000);
      client.once("message", (receivedTopic, payload) => {
        clearTimeout(timeout);
        if (receivedTopic !== topic || payload.toString() !== id) reject(new Error("MQTT lifecycle round trip mismatch"));
        else resolve();
      });
    });
    await client.publishAsync(topic, id, { qos: 1, retain: false });
    await received;
    if (config.persistence && !process.argv.includes("--liveness")) {
      const storage = await statfs(config.persistenceLocation);
      const availableBytes = storage.bavail * storage.bsize;
      if (availableBytes < config.minimumFreeBytes) throw new Error("MQTT persistence free space is below the readiness floor");
      const probe = `${config.persistenceLocation}.piphi-health-${process.pid}`;
      await execFileAsync("su-exec", ["mosquitto", "sh", "-c", "umask 077; : > \"$1\"; test -w \"$1\"; rm -f \"$1\"", "piphi-persistence-probe", probe], { timeout: 3_000 });
      const candidate = `${config.readinessStatePath}.candidate-${process.pid}`;
      await writeFile(candidate, `${JSON.stringify({ schema_version: 1, broker_id: config.brokerId, last_success_at: new Date().toISOString() })}\n`, { mode: 0o600 });
      await rename(candidate, config.readinessStatePath);
    }
  } finally {
    await client.endAsync();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
