import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type { BrokerConfig } from "./config.js";

function renderPasswordConfig(config: BrokerConfig): string[] {
  if (!config.username || !config.password) {
    return [];
  }

  return [
    "password_file " + config.passwordFile,
  ];
}

export function renderMosquittoConfig(config: BrokerConfig): string {
  const lines = [
    "listener " + config.port + " " + config.host,
    "allow_anonymous " + (config.allowAnonymous ? "true" : "false"),
    "persistence " + (config.persistence ? "true" : "false"),
    "persistence_location " + config.persistenceLocation,
    "log_dest " + config.logDest,
    ...renderPasswordConfig(config),
    "",
  ];

  return lines.join("\n");
}

export async function writeMosquittoConfig(config: BrokerConfig): Promise<void> {
  await mkdir(dirname(config.configOutputPath), { recursive: true });
  await writeFile(config.configOutputPath, renderMosquittoConfig(config), "utf8");
}

