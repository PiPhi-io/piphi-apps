export interface BrokerConfig {
  host: string;
  port: number;
  allowAnonymous: boolean;
  persistence: boolean;
  persistenceLocation: string;
  logDest: string;
  username: string | null;
  password: string | null;
  passwordFile: string;
  configOutputPath: string;
  topicPrefix: string;
}

const DEFAULTS = {
  host: "0.0.0.0",
  port: 1883,
  allowAnonymous: false,
  persistence: true,
  persistenceLocation: "/mosquitto/data/",
  logDest: "stdout",
  passwordFile: "/mosquitto/config/passwordfile",
  configOutputPath: "/mosquitto/config/mosquitto.conf",
  topicPrefix: "piphi",
} as const;

function readBoolean(rawValue: string | undefined, fallback: boolean): boolean {
  if (rawValue === undefined || rawValue.trim() === "") {
    return fallback;
  }

  const normalized = rawValue.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }

  throw new Error(`Invalid boolean value: ${rawValue}`);
}

function readPort(rawValue: string | undefined, fallback: number): number {
  if (rawValue === undefined || rawValue.trim() === "") {
    return fallback;
  }

  const parsed = Number.parseInt(rawValue, 10);
  if (Number.isNaN(parsed) || parsed <= 0 || parsed > 65535) {
    throw new Error(`Invalid MQTT port: ${rawValue}`);
  }

  return parsed;
}

function readManagedPort(env: NodeJS.ProcessEnv): number {
  if (env.PORT === undefined) return readPort(env.MQTT_PORT, DEFAULTS.port);
  if (!/^\d+$/.test(env.PORT)) throw new Error(`Invalid managed runtime PORT: ${env.PORT}`);
  const parsed = Number(env.PORT);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 65535) {
    throw new Error(`Invalid managed runtime PORT: ${env.PORT}`);
  }
  return parsed;
}

function readOptionalString(rawValue: string | undefined): string | null {
  if (rawValue === undefined) {
    return null;
  }

  const trimmed = rawValue.trim();
  return trimmed === "" ? null : trimmed;
}

export function loadBrokerConfig(
  env: NodeJS.ProcessEnv = process.env,
): BrokerConfig {
  const config = {
    host: env.MQTT_HOST?.trim() || DEFAULTS.host,
    port: readManagedPort(env),
    allowAnonymous: readBoolean(env.MQTT_ALLOW_ANONYMOUS, DEFAULTS.allowAnonymous),
    persistence: readBoolean(env.MQTT_PERSISTENCE, DEFAULTS.persistence),
    persistenceLocation:
      env.MQTT_PERSISTENCE_LOCATION?.trim() || DEFAULTS.persistenceLocation,
    logDest: env.MQTT_LOG_DEST?.trim() || DEFAULTS.logDest,
    username: readOptionalString(env.MQTT_USERNAME),
    password: readOptionalString(env.MQTT_PASSWORD),
    passwordFile: env.MQTT_PASSWORD_FILE?.trim() || DEFAULTS.passwordFile,
    configOutputPath:
      env.MQTT_CONFIG_OUTPUT?.trim() || DEFAULTS.configOutputPath,
    topicPrefix: env.MQTT_TOPIC_PREFIX?.trim() || DEFAULTS.topicPrefix,
  };

  if ((config.username && !config.password) || (!config.username && config.password)) {
    throw new Error("MQTT_USERNAME and MQTT_PASSWORD must be provided together");
  }

  if (!config.allowAnonymous && (!config.username || !config.password)) {
    throw new Error(
      "MQTT credentials are required when MQTT_ALLOW_ANONYMOUS is false",
    );
  }

  return config;
}
