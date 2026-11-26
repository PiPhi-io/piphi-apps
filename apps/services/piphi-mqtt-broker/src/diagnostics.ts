import { readFile, statfs } from "node:fs/promises";
import { connectAsync } from "mqtt";

import { confineBrokerInputPaths, loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy, OBSERVABILITY_TOPICS, readPrincipalPassword } from "./identity.js";

const METRIC_NAMES = new Map(OBSERVABILITY_TOPICS.map((topic) => [topic, topic.slice("$SYS/broker/".length).replaceAll("/", "_").replaceAll(" ", "_")]));

async function main(): Promise<void> {
  const config = await confineBrokerInputPaths(loadBrokerConfig());
  const policy = await loadIdentityPolicy(config);
  const health = policy.principals.find((principal) => principal.health);
  if (!health) throw new Error("Health principal is not configured");
  const password = await readPrincipalPassword(health, config);
  const host = process.env.MQTT_HEALTH_HOST?.trim() || "127.0.0.1";
  const protocol = config.tlsEnabled ? "mqtts" : "mqtt";
  const client = await connectAsync(`${protocol}://${host}:${config.port}`, {
    protocolVersion: 5,
    username: health.username,
    password,
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
  const metrics: Record<string, number | string> = {};
  try {
    const collected = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("Broker observability sample timed out")), Math.min(15_000, config.sysInterval * 2_000 + 2_000));
      client.on("message", (topic, payload) => {
        const name = METRIC_NAMES.get(topic as typeof OBSERVABILITY_TOPICS[number]);
        if (!name) return;
        const raw = payload.toString("utf8");
        metrics[name] = /^\d+$/.test(raw) ? Number(raw) : raw.slice(0, 128);
        if (metrics.uptime !== undefined && Object.keys(metrics).length >= 5) {
          clearTimeout(timeout);
          resolve();
        }
      });
    });
    await client.subscribeAsync([...OBSERVABILITY_TOPICS], { qos: 0 });
    await collected;
    const storage = await statfs(config.persistenceLocation);
    const readiness = JSON.parse(await readFile(config.readinessStatePath, "utf8")) as { broker_id?: unknown; last_success_at?: unknown };
    if (readiness.broker_id !== config.brokerId || typeof readiness.last_success_at !== "string") throw new Error("Readiness state is invalid");
    const lastSuccessAt = Date.parse(readiness.last_success_at);
    if (!Number.isFinite(lastSuccessAt)) throw new Error("Readiness state timestamp is invalid");
    const ageSeconds = Math.max(0, Math.floor((Date.now() - lastSuccessAt) / 1_000));
    process.stdout.write(`${JSON.stringify({
      schema_version: 1,
      broker_id: config.brokerId,
      status: ageSeconds <= config.readinessStaleAfterSeconds ? "ready" : "stale",
      sampled_at: new Date().toISOString(),
      readiness: { last_success_at: readiness.last_success_at, age_seconds: ageSeconds, stale_after_seconds: config.readinessStaleAfterSeconds },
      storage: { available_bytes: storage.bavail * storage.bsize, total_bytes: storage.blocks * storage.bsize, readiness_floor_bytes: config.minimumFreeBytes },
      broker: metrics,
    })}\n`);
  } finally {
    await client.endAsync();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
