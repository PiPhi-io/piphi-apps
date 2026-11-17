import { createHash } from "node:crypto";
import { chmod, readFile, writeFile } from "node:fs/promises";

import type { BrokerConfig } from "./config.js";

export interface BrokerPrincipal {
  username: string;
  passwordSecretFile: string;
  read: string[];
  write: string[];
  health: boolean;
  namespace: string;
}

export interface IdentityPolicy {
  schemaVersion: 1;
  principals: BrokerPrincipal[];
  sourceDigest: string;
}

function assertSecretPath(value: unknown, field: string): string {
  if (typeof value !== "string" || /[\r\n\0]/.test(value) || !["/run/secrets/", "/mosquitto/config/"].some((root) => value.startsWith(root))) {
    throw new Error(`${field} must be an absolute secret path`);
  }
  return value;
}

function assertUsername(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9._-]{1,128}$/.test(value)) throw new Error(`Invalid principal username: ${String(value)}`);
  return value;
}

function assertNamespace(value: unknown, field: string): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(value)) throw new Error(`${field} must be a single safe topic segment`);
  return value;
}

function inferNamespace(value: unknown, field: string, prefix: string): string {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${field} must contain at least one topic filter`);
  const namespaces = new Set(value.map((filter) => typeof filter === "string" ? filter.slice(`${prefix}/`.length).split("/", 1)[0] : ""));
  if (namespaces.size !== 1) throw new Error(`${field} must stay within one workload namespace`);
  return assertNamespace([...namespaces][0], `${field} namespace`);
}

function assertFilters(value: unknown, field: string, prefix: string, namespace: string): string[] {
  if (!Array.isArray(value) || value.length === 0) throw new Error(`${field} must contain at least one topic filter`);
  return value.map((filter) => {
    if (typeof filter !== "string" || /[\r\n\0]/.test(filter) || !filter.startsWith(`${prefix}/${namespace}/`) || filter.includes("$SYS") || filter.includes("$CONTROL")) {
      throw new Error(`${field} must stay beneath ${prefix}/${namespace}/ and cannot access reserved topics`);
    }
    const segments = filter.split("/");
    if (segments.some((segment, index) => segment.includes("#") && (segment !== "#" || index !== segments.length - 1)) || segments.some((segment) => segment.includes("+") && segment !== "+")) {
      throw new Error(`Invalid MQTT topic filter in ${field}: ${filter}`);
    }
    return filter;
  });
}

export async function loadIdentityPolicy(config: BrokerConfig): Promise<IdentityPolicy> {
  if (!config.authPolicyFile) {
    if (!config.username) throw new Error("Broker identity is not configured");
    return {
      schemaVersion: 1,
      sourceDigest: "legacy-single-principal",
      principals: [{
        username: config.username,
        passwordSecretFile: config.passwordSecretFile ?? "environment:MQTT_PASSWORD",
        read: [`${config.topicPrefix}/#`],
        write: [`${config.topicPrefix}/#`],
        health: true,
        namespace: "legacy",
      }],
    };
  }

  const raw = await readFile(config.authPolicyFile, "utf8");
  return parseIdentityPolicy(raw, config);
}

export function parseIdentityPolicy(raw: string, config: BrokerConfig): IdentityPolicy {
  let document: Record<string, unknown>;
  try {
    document = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new Error("MQTT auth policy is not valid JSON");
  }
  if (document.schema_version !== 1 || !Array.isArray(document.principals) || document.principals.length === 0) throw new Error("MQTT auth policy requires schema_version 1 and at least one principal");
  const usernames = new Set<string>();
  const namespaces = new Set<string>();
  const principals = document.principals.map((value, index) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid principal at index ${index}`);
    const item = value as Record<string, unknown>;
    const username = assertUsername(item.username);
    if (usernames.has(username)) throw new Error(`Duplicate principal username: ${username}`);
    usernames.add(username);
    const namespace = item.namespace === undefined
      ? inferNamespace([...(Array.isArray(item.read) ? item.read : []), ...(Array.isArray(item.write) ? item.write : [])], `principals[${index}]`, config.topicPrefix)
      : assertNamespace(item.namespace, `principals[${index}].namespace`);
    if (namespaces.has(namespace)) throw new Error(`Duplicate principal namespace: ${namespace}`);
    namespaces.add(namespace);
    const health = item.health === true;
    if ((health && namespace !== "_health") || (!health && namespace === "_health")) throw new Error("Only the health principal may use the _health namespace");
    return {
      username,
      passwordSecretFile: assertSecretPath(item.password_secret_file, `principals[${index}].password_secret_file`),
      read: assertFilters(item.read, `principals[${index}].read`, config.topicPrefix, namespace),
      write: assertFilters(item.write, `principals[${index}].write`, config.topicPrefix, namespace),
      health,
      namespace,
    };
  });
  if (principals.filter((principal) => principal.health).length !== 1) throw new Error("MQTT auth policy requires exactly one health principal");
  return { schemaVersion: 1, principals, sourceDigest: createHash("sha256").update(raw).digest("hex") };
}

export function renderIdentityAcl(policy: IdentityPolicy): string {
  const lines: string[] = [];
  for (const principal of policy.principals) {
    lines.push(`user ${principal.username}`);
    lines.push("topic deny readwrite $SYS/#", "topic deny readwrite $CONTROL/#");
    for (const filter of principal.read) lines.push(`topic read ${filter}`);
    for (const filter of principal.write) lines.push(`topic write ${filter}`);
    lines.push("");
  }
  return lines.join("\n");
}

async function readPrincipalPassword(principal: BrokerPrincipal, config: BrokerConfig): Promise<string> {
  const raw = principal.passwordSecretFile === "environment:MQTT_PASSWORD"
    ? config.password
    : await readFile(principal.passwordSecretFile, "utf8");
  const password = raw?.replace(/[\r\n]+$/, "") ?? "";
  if (!password || /[\r\n\0]/.test(password)) throw new Error(`Password secret for ${principal.username} is empty or malformed`);
  return password;
}

export async function writeIdentityCandidates(config: BrokerConfig, policy: IdentityPolicy): Promise<void> {
  const passwordCandidate = `${config.passwordFile}.candidate`;
  const credentialLines: string[] = [];
  for (const principal of policy.principals) credentialLines.push(`${principal.username}:${await readPrincipalPassword(principal, config)}`);
  await writeFile(passwordCandidate, `${credentialLines.join("\n")}\n`, { encoding: "utf8", mode: 0o600 });
  await chmod(passwordCandidate, 0o600);
  credentialLines.fill("");
  const aclCandidate = `${config.aclFile}.candidate`;
  await writeFile(aclCandidate, renderIdentityAcl(policy), { encoding: "utf8", mode: 0o640 });
  await chmod(aclCandidate, 0o640);
}
