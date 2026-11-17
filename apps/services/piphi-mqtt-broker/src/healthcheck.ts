import { access, readFile, rm, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { connectAsync } from "mqtt";

import { loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy } from "./identity.js";

async function main(): Promise<void> {
  const config = loadBrokerConfig();
  const policy = await loadIdentityPolicy(config);
  const health = policy.principals.find((principal) => principal.health);
  if (!health) throw new Error("Health principal is not configured");
  const password = health.passwordSecretFile === "environment:MQTT_PASSWORD"
    ? config.password
    : (await readFile(health.passwordSecretFile, "utf8")).trimEnd();
  const host = process.env.MQTT_HEALTH_HOST?.trim() || "127.0.0.1";
  const protocol = config.tlsEnabled ? "mqtts" : "mqtt";
  const id = randomUUID();
  const topic = `${config.topicPrefix}/_health/${id}`;
  const client = await connectAsync(`${protocol}://${host}:${config.port}`, {
    protocolVersion: 5,
    username: health.username,
    password: password ?? undefined,
    connectTimeout: 3_000,
    reconnectPeriod: 0,
    rejectUnauthorized: true,
    servername: process.env.MQTT_TLS_SERVER_NAME?.trim() || undefined,
    ca: config.tlsCaFile ? await readFile(config.tlsCaFile) : undefined,
    cert: config.tlsRequireClientCertificate && config.healthTlsCertFile ? await readFile(config.healthTlsCertFile) : undefined,
    key: config.tlsRequireClientCertificate && config.healthTlsKeyFile ? await readFile(config.healthTlsKeyFile) : undefined,
  });

  try {
    if (process.argv.includes("--liveness")) return;
    await client.subscribeAsync(topic, { qos: 1 });
    const received = new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("MQTT readiness round trip timed out")), 3_000);
      client.once("message", (receivedTopic, payload) => {
        clearTimeout(timeout);
        if (receivedTopic !== topic || payload.toString() !== id) reject(new Error("MQTT readiness round trip mismatch"));
        else resolve();
      });
    });
    await client.publishAsync(topic, id, { qos: 1, retain: false });
    await received;
    if (config.persistence) {
      const probe = `${config.persistenceLocation}.piphi-health-${randomUUID()}`;
      try {
        await writeFile(probe, "", { mode: 0o600, flag: "wx" });
        await access(probe);
      } finally {
        await rm(probe, { force: true }).catch(() => undefined);
      }
    }
  } finally {
    await client.endAsync();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
