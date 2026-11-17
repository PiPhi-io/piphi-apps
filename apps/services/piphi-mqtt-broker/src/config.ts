export interface BrokerConfig {
  host: string;
  port: number;
  allowAnonymous: boolean;
  allowPlaintext: boolean;
  persistence: boolean;
  persistenceLocation: string;
  logDest: "stdout" | "stderr";
  username: string | null;
  password: string | null;
  passwordSecretFile: string | null;
  authPolicyFile: string | null;
  identityRoot: string;
  identityCandidateDir: string;
  passwordFile: string;
  aclFile: string;
  configOutputPath: string;
  topicPrefix: string;
  tlsEnabled: boolean;
  tlsCaFile: string | null;
  tlsCertFile: string | null;
  tlsKeyFile: string | null;
  tlsRequireClientCertificate: boolean;
  healthTlsCertFile: string | null;
  healthTlsKeyFile: string | null;
  maxConnections: number;
  maxPacketSize: number;
  messageSizeLimit: number;
  maxInflightMessages: number;
  maxQueuedMessages: number;
  maxQueuedBytes: number;
  memoryLimit: number;
  maxKeepalive: number;
  persistentClientExpiration: string;
}

const DEFAULTS = {
  host: "0.0.0.0",
  port: 1883,
  allowAnonymous: false,
  allowPlaintext: false,
  persistence: true,
  persistenceLocation: "/mosquitto/data/",
  logDest: "stdout" as const,
  identityRoot: "/mosquitto/config/identity",
  configOutputPath: "/mosquitto/config/mosquitto.conf",
  topicPrefix: "piphi",
  tlsEnabled: false,
  maxConnections: 256,
  maxPacketSize: 1_048_576,
  messageSizeLimit: 1_048_576,
  maxInflightMessages: 32,
  maxQueuedMessages: 1_024,
  maxQueuedBytes: 16_777_216,
  memoryLimit: 268_435_456,
  maxKeepalive: 300,
  persistentClientExpiration: "7d",
} as const;

function readBoolean(rawValue: string | undefined, fallback: boolean): boolean {
  if (rawValue === undefined || rawValue.trim() === "") return fallback;
  const normalized = rawValue.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "off"].includes(normalized)) return false;
  throw new Error(`Invalid boolean value: ${rawValue}`);
}

function readInteger(rawValue: string | undefined, fallback: number, name: string): number {
  if (rawValue === undefined || rawValue.trim() === "") return fallback;
  if (!/^\d+$/.test(rawValue.trim())) throw new Error(`Invalid ${name}: ${rawValue}`);
  const parsed = Number(rawValue);
  if (!Number.isSafeInteger(parsed) || parsed < 1) throw new Error(`Invalid ${name}: ${rawValue}`);
  return parsed;
}

function readBoundedInteger(rawValue: string | undefined, fallback: number, name: string, maximum: number): number {
  const parsed = readInteger(rawValue, fallback, name);
  if (parsed > maximum) throw new Error(`Invalid ${name}: value exceeds ${maximum}`);
  return parsed;
}

function readPort(rawValue: string | undefined, fallback: number, name: string): number {
  const parsed = readInteger(rawValue, fallback, name);
  if (parsed > 65535) throw new Error(`Invalid ${name}: ${rawValue}`);
  return parsed;
}

function readManagedPort(env: NodeJS.ProcessEnv): number {
  return env.PORT === undefined
    ? readPort(env.MQTT_PORT, DEFAULTS.port, "MQTT port")
    : readPort(env.PORT, DEFAULTS.port, "managed runtime PORT");
}

function optional(rawValue: string | undefined): string | null {
  const value = rawValue?.trim();
  return value ? value : null;
}

function safeToken(value: string, name: string, pattern: RegExp): string {
  if (/[\r\n\0]/.test(value) || !pattern.test(value)) throw new Error(`Invalid ${name}: ${value}`);
  return value;
}

function absolutePath(value: string, name: string, allowedRoots: readonly string[]): string {
  if (/[\r\n\0]/.test(value) || !value.startsWith("/") || value.includes("/../") || value.endsWith("/..") || !allowedRoots.some((root) => value.startsWith(root))) {
    throw new Error(`Invalid ${name}: path must be absolute and under ${allowedRoots.join(" or ")}`);
  }
  return value;
}

export function loadBrokerConfig(env: NodeJS.ProcessEnv = process.env): BrokerConfig {
  const tlsEnabled = readBoolean(env.MQTT_TLS_ENABLED, DEFAULTS.tlsEnabled);
  const identityRoot = absolutePath(env.MQTT_IDENTITY_ROOT?.trim() || DEFAULTS.identityRoot, "MQTT_IDENTITY_ROOT", ["/mosquitto/config/"]);
  const config: BrokerConfig = {
    host: safeToken(env.MQTT_HOST?.trim() || DEFAULTS.host, "MQTT_HOST", /^[A-Za-z0-9:._-]+$/),
    port: readManagedPort(env),
    allowAnonymous: readBoolean(env.MQTT_ALLOW_ANONYMOUS, DEFAULTS.allowAnonymous),
    allowPlaintext: readBoolean(env.MQTT_ALLOW_PLAINTEXT, DEFAULTS.allowPlaintext),
    persistence: readBoolean(env.MQTT_PERSISTENCE, DEFAULTS.persistence),
    persistenceLocation: absolutePath(env.MQTT_PERSISTENCE_LOCATION?.trim() || DEFAULTS.persistenceLocation, "MQTT_PERSISTENCE_LOCATION", ["/mosquitto/data/"]),
    logDest: safeToken(env.MQTT_LOG_DEST?.trim() || DEFAULTS.logDest, "MQTT_LOG_DEST", /^(stdout|stderr)$/) as "stdout" | "stderr",
    username: optional(env.MQTT_USERNAME),
    password: optional(env.MQTT_PASSWORD),
    passwordSecretFile: optional(env.MQTT_PASSWORD_SECRET_FILE),
    authPolicyFile: optional(env.MQTT_AUTH_POLICY_FILE),
    identityRoot,
    identityCandidateDir: absolutePath(env.MQTT_IDENTITY_CANDIDATE_DIR?.trim() || `${identityRoot}/candidate`, "MQTT_IDENTITY_CANDIDATE_DIR", [`${identityRoot}/`]),
    passwordFile: `${identityRoot}/current/passwordfile`,
    aclFile: `${identityRoot}/current/aclfile`,
    configOutputPath: absolutePath(env.MQTT_CONFIG_OUTPUT?.trim() || DEFAULTS.configOutputPath, "MQTT_CONFIG_OUTPUT", ["/mosquitto/config/"]),
    topicPrefix: safeToken(env.MQTT_TOPIC_PREFIX?.trim() || DEFAULTS.topicPrefix, "MQTT_TOPIC_PREFIX", /^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/),
    tlsEnabled,
    tlsCaFile: optional(env.MQTT_TLS_CA_FILE),
    tlsCertFile: optional(env.MQTT_TLS_CERT_FILE),
    tlsKeyFile: optional(env.MQTT_TLS_KEY_FILE),
    tlsRequireClientCertificate: readBoolean(env.MQTT_TLS_REQUIRE_CLIENT_CERTIFICATE, false),
    healthTlsCertFile: optional(env.MQTT_HEALTH_TLS_CERT_FILE),
    healthTlsKeyFile: optional(env.MQTT_HEALTH_TLS_KEY_FILE),
    maxConnections: readBoundedInteger(env.MQTT_MAX_CONNECTIONS, DEFAULTS.maxConnections, "MQTT_MAX_CONNECTIONS", 100_000),
    maxPacketSize: readBoundedInteger(env.MQTT_MAX_PACKET_SIZE, DEFAULTS.maxPacketSize, "MQTT_MAX_PACKET_SIZE", 268_435_455),
    messageSizeLimit: readBoundedInteger(env.MQTT_MESSAGE_SIZE_LIMIT, DEFAULTS.messageSizeLimit, "MQTT_MESSAGE_SIZE_LIMIT", 268_435_455),
    maxInflightMessages: readBoundedInteger(env.MQTT_MAX_INFLIGHT_MESSAGES, DEFAULTS.maxInflightMessages, "MQTT_MAX_INFLIGHT_MESSAGES", 65_535),
    maxQueuedMessages: readBoundedInteger(env.MQTT_MAX_QUEUED_MESSAGES, DEFAULTS.maxQueuedMessages, "MQTT_MAX_QUEUED_MESSAGES", 1_000_000),
    maxQueuedBytes: readBoundedInteger(env.MQTT_MAX_QUEUED_BYTES, DEFAULTS.maxQueuedBytes, "MQTT_MAX_QUEUED_BYTES", 4_294_967_295),
    memoryLimit: readBoundedInteger(env.MQTT_MEMORY_LIMIT, DEFAULTS.memoryLimit, "MQTT_MEMORY_LIMIT", 4_294_967_295),
    maxKeepalive: readBoundedInteger(env.MQTT_MAX_KEEPALIVE, DEFAULTS.maxKeepalive, "MQTT_MAX_KEEPALIVE", 65_535),
    persistentClientExpiration: safeToken(env.MQTT_PERSISTENT_CLIENT_EXPIRATION?.trim() || DEFAULTS.persistentClientExpiration, "MQTT_PERSISTENT_CLIENT_EXPIRATION", /^[1-9]\d*[hdwmy]$/),
  };

  if (config.username) safeToken(config.username, "MQTT_USERNAME", /^[A-Za-z0-9._-]{1,128}$/);
  if (config.password && /[\r\n\0]/.test(config.password)) throw new Error("Invalid MQTT_PASSWORD");
  if (config.authPolicyFile && (config.username || config.password || config.passwordSecretFile)) throw new Error("MQTT_AUTH_POLICY_FILE cannot be combined with legacy MQTT credentials");
  if (config.username && !config.password && !config.passwordSecretFile) throw new Error("MQTT_USERNAME requires MQTT_PASSWORD or MQTT_PASSWORD_SECRET_FILE");
  if (!config.username && (config.password || config.passwordSecretFile)) throw new Error("MQTT_USERNAME is required with a password");
  if (!config.allowAnonymous && !config.username && !config.authPolicyFile) throw new Error("MQTT credentials or MQTT_AUTH_POLICY_FILE are required when MQTT_ALLOW_ANONYMOUS is false");
  if (config.allowAnonymous) throw new Error("Anonymous MQTT is not supported");
  if (!tlsEnabled && !config.allowPlaintext) throw new Error("Plaintext MQTT must be explicitly enabled with MQTT_ALLOW_PLAINTEXT=true");
  if (tlsEnabled && (!config.tlsCertFile || !config.tlsKeyFile)) throw new Error("MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE are required when TLS is enabled");
  for (const [value, name] of [[config.tlsCaFile, "MQTT_TLS_CA_FILE"], [config.tlsCertFile, "MQTT_TLS_CERT_FILE"], [config.tlsKeyFile, "MQTT_TLS_KEY_FILE"], [config.healthTlsCertFile, "MQTT_HEALTH_TLS_CERT_FILE"], [config.healthTlsKeyFile, "MQTT_HEALTH_TLS_KEY_FILE"], [config.passwordSecretFile, "MQTT_PASSWORD_SECRET_FILE"], [config.authPolicyFile, "MQTT_AUTH_POLICY_FILE"]] as const) {
    if (value) absolutePath(value, name, ["/run/secrets/", "/mosquitto/config/"]);
  }
  if (config.tlsRequireClientCertificate && !config.tlsCaFile) throw new Error("MQTT_TLS_CA_FILE is required for client certificate authentication");
  if (config.tlsRequireClientCertificate && (!config.healthTlsCertFile || !config.healthTlsKeyFile)) throw new Error("MQTT_HEALTH_TLS_CERT_FILE and MQTT_HEALTH_TLS_KEY_FILE are required for authenticated mTLS health checks");

  return config;
}

function resolvedWithin(root: string, candidate: string): boolean {
  const child = relative(root, candidate);
  return child !== "" && child !== ".." && !child.startsWith("../") && !isAbsolute(child);
}

async function confinedRealpath(value: string, name: string): Promise<string> {
  const candidate = await realpath(value);
  for (const root of ["/run/secrets", "/mosquitto/config"]) {
    const resolvedRoot = await realpath(root).catch(() => null);
    if (resolvedRoot && resolvedWithin(resolvedRoot, candidate)) return candidate;
  }
  throw new Error(`${name} resolves outside an allowed secret directory`);
}

export async function confineBrokerInputPaths(config: BrokerConfig): Promise<BrokerConfig> {
  const fields = [
    ["authPolicyFile", "MQTT_AUTH_POLICY_FILE"],
    ["passwordSecretFile", "MQTT_PASSWORD_SECRET_FILE"],
    ["tlsCaFile", "MQTT_TLS_CA_FILE"],
    ["tlsCertFile", "MQTT_TLS_CERT_FILE"],
    ["tlsKeyFile", "MQTT_TLS_KEY_FILE"],
    ["healthTlsCertFile", "MQTT_HEALTH_TLS_CERT_FILE"],
    ["healthTlsKeyFile", "MQTT_HEALTH_TLS_KEY_FILE"],
  ] as const;
  for (const [field, name] of fields) {
    const value = config[field];
    if (value) config[field] = await confinedRealpath(value, name);
  }
  return config;
}
import { realpath } from "node:fs/promises";
import { isAbsolute, relative } from "node:path";
