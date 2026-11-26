import { createHash } from "node:crypto";
import { chmod, lstat, mkdir, open, readFile, readdir, readlink, realpath, rename, rm, stat, symlink, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { isAbsolute, relative, resolve } from "node:path";

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

export const OBSERVABILITY_TOPICS = [
  "$SYS/broker/uptime",
  "$SYS/broker/clients/connected",
  "$SYS/broker/clients/disconnected",
  "$SYS/broker/clients/maximum",
  "$SYS/broker/clients/total",
  "$SYS/broker/messages/dropped",
  "$SYS/broker/messages/stored",
  "$SYS/broker/retained messages/count",
  "$SYS/broker/store/messages/bytes",
  "$SYS/broker/store/messages/count",
  "$SYS/broker/subscriptions/count",
] as const;

function assertSecretPath(value: unknown, field: string): string {
  if (typeof value !== "string" || /[\r\n\0]/.test(value) || !isAbsolute(value) || !["/run/secrets", "/mosquitto/config"].some((root) => isContainedPath(root, resolve(value)))) {
    throw new Error(`${field} must be an absolute secret path`);
  }
  return value;
}

function isContainedPath(root: string, candidate: string): boolean {
  const child = relative(root, candidate);
  return child !== "" && child !== ".." && !child.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) && !isAbsolute(child);
}

async function resolveSecretPath(value: string): Promise<string> {
  const candidate = await realpath(value);
  for (const root of ["/run/secrets", "/mosquitto/config"]) {
    const resolvedRoot = await realpath(root).catch(() => null);
    if (resolvedRoot && isContainedPath(resolvedRoot, candidate)) return candidate;
  }
  throw new Error("Principal password secret resolves outside an allowed secret directory");
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
    const passwordSecretFile = config.passwordSecretFile ? await resolveSecretPath(config.passwordSecretFile) : "environment:MQTT_PASSWORD";
    return {
      schemaVersion: 1,
      sourceDigest: "legacy-single-principal",
      principals: [{
        username: config.username,
        passwordSecretFile,
        read: [`${config.topicPrefix}/#`],
        write: [`${config.topicPrefix}/#`],
        health: true,
        namespace: "legacy",
      }],
    };
  }

  const policyStat = await stat(config.authPolicyFile);
  if (!policyStat.isFile() || policyStat.size > 1_048_576) throw new Error("MQTT auth policy must be a regular file no larger than 1 MiB");
  const raw = await readFile(config.authPolicyFile, "utf8");
  const policy = parseIdentityPolicy(raw, config);
  for (const principal of policy.principals) principal.passwordSecretFile = await resolveSecretPath(principal.passwordSecretFile);
  return policy;
}

export function parseIdentityPolicy(raw: string, config: BrokerConfig): IdentityPolicy {
  let document: Record<string, unknown>;
  try {
    document = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new Error("MQTT auth policy is not valid JSON");
  }
  if (document.schema_version !== 1 || !Array.isArray(document.principals) || document.principals.length === 0) throw new Error("MQTT auth policy requires schema_version 1 and at least one principal");
  if (document.principals.length > config.maxConnections) throw new Error(`MQTT auth policy exceeds the ${config.maxConnections} principal limit`);
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
    if (principal.health) {
      for (const topic of OBSERVABILITY_TOPICS) lines.push(`topic read ${topic}`);
    } else {
      lines.push("topic deny $SYS/#");
    }
    lines.push("topic deny $CONTROL/#");
    for (const filter of principal.read) lines.push(`topic read ${filter}`);
    for (const filter of principal.write) lines.push(`topic write ${filter}`);
    lines.push("");
  }
  return lines.join("\n");
}

export async function readPrincipalPassword(principal: BrokerPrincipal, config: BrokerConfig): Promise<string> {
  if (principal.passwordSecretFile !== "environment:MQTT_PASSWORD") {
    const secretStat = await stat(principal.passwordSecretFile);
    if (!secretStat.isFile() || secretStat.size > 8_192) throw new Error(`Password secret for ${principal.username} must be a regular file no larger than 8 KiB`);
  }
  const raw = principal.passwordSecretFile === "environment:MQTT_PASSWORD" ? config.password : await readFile(principal.passwordSecretFile, "utf8");
  const password = raw?.replace(/[\r\n]+$/, "") ?? "";
  if (!password || /[\r\n\0]/.test(password)) throw new Error(`Password secret for ${principal.username} is empty or malformed`);
  return password;
}

export async function writeIdentityCandidates(config: BrokerConfig, policy: IdentityPolicy): Promise<void> {
  await rm(config.identityCandidateDir, { recursive: true, force: true });
  await mkdir(config.identityCandidateDir, { recursive: true, mode: 0o750 });
  const passwordCandidate = `${config.identityCandidateDir}/passwordfile`;
  const passwordHandle = await open(passwordCandidate, "wx", 0o600);
  try {
    for (const principal of policy.principals) await passwordHandle.write(`${principal.username}:${await readPrincipalPassword(principal, config)}\n`);
    await passwordHandle.sync();
  } finally {
    await passwordHandle.close();
  }
  await chmod(passwordCandidate, 0o600);
  const aclCandidate = `${config.identityCandidateDir}/aclfile`;
  await writeFile(aclCandidate, renderIdentityAcl(policy), { encoding: "utf8", mode: 0o640 });
  await chmod(aclCandidate, 0o640);
}

interface IdentityTransaction {
  previous: string | null;
  next: string;
}

function markerPath(config: BrokerConfig): string {
  return `${config.identityRoot}/transaction.json`;
}

async function syncPath(path: string): Promise<void> {
  const handle = await open(path, "r");
  try { await handle.sync(); } finally { await handle.close(); }
}

async function currentTarget(config: BrokerConfig): Promise<string | null> {
  try {
    return await readlink(`${config.identityRoot}/current`);
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

function validGenerationTarget(value: unknown): value is string {
  return typeof value === "string" && /^generations\/generation-[A-Za-z0-9-]+$/.test(value);
}

async function assertValidGeneration(config: BrokerConfig, target: string): Promise<void> {
  if (!validGenerationTarget(target)) throw new Error("Identity generation target is invalid");
  const base = `${config.identityRoot}/${target}`;
  const password = await lstat(`${base}/passwordfile`).catch(() => null);
  const acl = await lstat(`${base}/aclfile`).catch(() => null);
  if (!password?.isFile() || !acl?.isFile()) throw new Error("Identity generation is incomplete");
}

async function swapCurrent(config: BrokerConfig, target: string): Promise<void> {
  const temporary = `${config.identityRoot}/.current-${randomUUID()}`;
  await symlink(target, temporary);
  await rename(temporary, `${config.identityRoot}/current`);
  await syncPath(config.identityRoot);
}

export async function activateIdentityCandidate(config: BrokerConfig): Promise<void> {
  await mkdir(`${config.identityRoot}/generations`, { recursive: true, mode: 0o750 });
  await syncPath(`${config.identityCandidateDir}/passwordfile`);
  await syncPath(`${config.identityCandidateDir}/aclfile`);
  const generationName = `generation-${Date.now()}-${randomUUID()}`;
  const generationPath = `${config.identityRoot}/generations/${generationName}`;
  await rename(config.identityCandidateDir, generationPath);
  await syncPath(`${config.identityRoot}/generations`);
  const transaction: IdentityTransaction = { previous: await currentTarget(config), next: `generations/${generationName}` };
  if (transaction.previous) await assertValidGeneration(config, transaction.previous);
  const temporaryMarker = `${config.identityRoot}/.transaction-${randomUUID()}.tmp`;
  await writeFile(temporaryMarker, `${JSON.stringify(transaction)}\n`, { mode: 0o600, flag: "wx" });
  await syncPath(temporaryMarker);
  if (process.env.PIPHI_TEST_CRASH_BEFORE_IDENTITY_MARKER_RENAME === "true") process.exit(87);
  await rename(temporaryMarker, markerPath(config));
  await syncPath(config.identityRoot);
  await swapCurrent(config, transaction.next);
  if (process.env.PIPHI_TEST_CRASH_AFTER_IDENTITY_SWAP === "true") process.exit(86);
}

async function readTransaction(config: BrokerConfig): Promise<IdentityTransaction | null> {
  let raw: string;
  try {
    raw = await readFile(markerPath(config), "utf8");
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  let transaction: Partial<IdentityTransaction>;
  try {
    transaction = JSON.parse(raw) as Partial<IdentityTransaction>;
  } catch {
    throw new Error("Identity transaction marker is malformed");
  }
  if ((transaction.previous !== null && !validGenerationTarget(transaction.previous)) || !validGenerationTarget(transaction.next)) {
    throw new Error("Identity transaction marker is invalid");
  }
  return transaction as IdentityTransaction;
}

export async function rollbackIdentityTransaction(config: BrokerConfig): Promise<void> {
  const transaction = await readTransaction(config);
  if (!transaction) return;
  if (transaction.previous) {
    await assertValidGeneration(config, transaction.previous);
    await swapCurrent(config, transaction.previous);
  }
  else await rm(`${config.identityRoot}/current`, { force: true });
  await rm(markerPath(config), { force: true });
  await syncPath(config.identityRoot);
}

export async function commitIdentityTransaction(config: BrokerConfig): Promise<void> {
  await rm(markerPath(config), { force: true });
  await syncPath(config.identityRoot);
}

export async function recoverIdentityTransaction(config: BrokerConfig): Promise<void> {
  await mkdir(config.identityRoot, { recursive: true, mode: 0o750 });
  await rollbackIdentityTransaction(config);
  const current = `${config.identityRoot}/current`;
  const entries = await lstat(current).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return null;
    throw error;
  });
  if (entries && !entries.isSymbolicLink()) throw new Error("Identity current pointer must be a symbolic link");
  const target = entries ? await readlink(current) : null;
  if (target) await assertValidGeneration(config, target);
  await rm(config.identityCandidateDir, { recursive: true, force: true });
  const temporaryMarkers = await readdir(config.identityRoot);
  await Promise.all(temporaryMarkers.filter((name) => /^\.transaction-.*\.tmp$/.test(name)).map((name) => rm(`${config.identityRoot}/${name}`, { force: true })));
  await syncPath(config.identityRoot);
}
