import { readFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { promisify } from "node:util";
import { connectAsync } from "mqtt";

import { confineBrokerInputPaths, loadBrokerConfig } from "./config.js";
import { loadIdentityPolicy } from "./identity.js";

const execFileAsync = promisify(execFile);

async function main(): Promise<void> {
  const config = await confineBrokerInputPaths(loadBrokerConfig());
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
      const probe = `${config.persistenceLocation}.piphi-health-${randomUUID()}`;
      await execFileAsync("su-exec", ["mosquitto", "sh", "-c", "umask 077; : > \"$1\"; test -w \"$1\"; rm -f \"$1\"", "piphi-persistence-probe", probe], { timeout: 3_000 });
    }
  } finally {
    await client.endAsync();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
});
