import { chmod, mkdir, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type { BrokerConfig } from "./config.js";

export function renderAcl(config: BrokerConfig): string {
  if (!config.username) return "";
  return [`user ${config.username}`, `topic readwrite ${config.topicPrefix}/#`, ""].join("\n");
}

export function renderMosquittoConfig(config: BrokerConfig): string {
  const lines = [
    `listener ${config.port} ${config.host}`,
    `allow_anonymous ${config.allowAnonymous ? "true" : "false"}`,
    `persistence ${config.persistence ? "true" : "false"}`,
    `persistence_location ${config.persistenceLocation}`,
    `persistent_client_expiration ${config.persistentClientExpiration}`,
    `log_dest ${config.logDest}`,
    "log_type error",
    "log_type warning",
    "log_type notice",
    "connection_messages true",
    `max_connections ${config.maxConnections}`,
    `max_packet_size ${config.maxPacketSize}`,
    `message_size_limit ${config.messageSizeLimit}`,
    `max_inflight_messages ${config.maxInflightMessages}`,
    `max_queued_messages ${config.maxQueuedMessages}`,
    `max_queued_bytes ${config.maxQueuedBytes}`,
    `memory_limit ${config.memoryLimit}`,
  ];
  if (config.username) lines.push(`password_file ${config.passwordFile}`, `acl_file ${config.aclFile}`);
  if (config.tlsEnabled) {
    lines.push(`certfile ${config.tlsCertFile}`, `keyfile ${config.tlsKeyFile}`, "tls_version tlsv1.2");
    if (config.tlsCaFile) lines.push(`cafile ${config.tlsCaFile}`);
    if (config.tlsRequireClientCertificate) lines.push("require_certificate true", "use_identity_as_username true");
  }
  lines.push("");
  return lines.join("\n");
}

async function atomicWrite(path: string, contents: string, mode: number): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const candidate = `${path}.candidate`;
  await writeFile(candidate, contents, { encoding: "utf8", mode });
  await chmod(candidate, mode);
  await rename(candidate, path);
}

export async function writeMosquittoConfig(config: BrokerConfig): Promise<void> {
  await atomicWrite(config.configOutputPath, renderMosquittoConfig(config), 0o640);
  if (config.username) await atomicWrite(config.aclFile, renderAcl(config), 0o640);
}
