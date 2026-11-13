import { Driver, libVersion, NodeStatus } from "zwave-js";

import { normalizeNodeEvent, sanitizeZWaveValue } from "./transport.js";
import type {
  DeviceConfig,
  DriverCommand,
  DriverSession,
  DriverSnapshot,
  ZWaveNodeSnapshot,
  ZWaveTransportEvent,
  ZWaveValueId,
} from "./types.js";

const NODE_EVENTS = [
  "value added",
  "value updated",
  "value removed",
  "value notification",
  "metadata updated",
  "notification",
  "interview started",
  "interview completed",
  "interview failed",
  "ready",
  "wake up",
  "sleep",
  "dead",
  "alive",
  "firmware update progress",
  "firmware update finished",
] as const;

const SENSITIVE_VALUE_TOKEN = /(security|network.?key|credential|token|secret|password|dsk|raw.?frame|nvm)/i;

type NodeLike = {
  id: number;
  name?: string;
  location?: string;
  manufacturerId?: number;
  productType?: number;
  productId?: number;
  firmwareVersion?: string;
  lastSeen?: Date;
  ready?: boolean;
  isReady?: boolean;
  status?: number | string;
  getDefinedValueIDs(): Array<{
    commandClass: number;
    endpoint?: number;
    property: string | number;
    propertyKey?: string | number;
    propertyName?: string;
    propertyKeyName?: string;
  }>;
  getValue(valueId: Record<string, unknown>): unknown;
  getValueTimestamp(valueId: Record<string, unknown>): number | undefined;
  getValueMetadata(valueId: Record<string, unknown>): Record<string, unknown>;
  setValue(valueId: Record<string, unknown>, value: unknown): Promise<unknown>;
  refreshInfo(): Promise<void>;
  refreshValues(): Promise<void>;
  interview(): Promise<void>;
  ping(tryReallyHard?: boolean): Promise<boolean>;
};

type DriverLike = {
  controller: {
    homeId?: number;
    ownNodeId?: number;
    nodes: Iterable<[number, NodeLike]>;
  };
  on(event: string, callback: (...args: unknown[]) => void): DriverLike;
  start(): Promise<void>;
  destroy(): Promise<void>;
};

export class ZWaveJsDriverSession implements DriverSession {
  private driver?: DriverLike;
  private lifecycle: DriverSnapshot["lifecycle"] = "stopped";
  private driverReady = false;
  private controllerReady = false;
  private reconnectCount = 0;
  private lastEventAt?: string;
  private lastErrorCode?: string;
  private recoveryTimer?: NodeJS.Timeout;
  private recoveryBackoffMs = 1_000;
  private stopRequested = false;

  constructor(
    private readonly config: DeviceConfig,
    private readonly onEvent: (event: Omit<ZWaveTransportEvent, "sequence">) => void,
  ) {}

  async start(): Promise<void> {
    if (this.driver) return;
    this.stopRequested = false;
    if (this.recoveryTimer) clearTimeout(this.recoveryTimer);
    this.recoveryTimer = undefined;
    this.lifecycle = "starting";
    this.lastErrorCode = undefined;
    const driver = new Driver(this.config.controller_path, {
      storage: {
        cacheDir: process.env.PIPHI_ZWAVE_CACHE_DIR ?? "/var/lib/piphi/zwave-js/cache",
        lockDir: process.env.PIPHI_ZWAVE_LOCK_DIR ?? "/var/lib/piphi/zwave-js/locks",
        throttle: "normal",
      },
      securityKeys: securityKeysFromEnvironment("PIPHI_ZWAVE"),
      securityKeysLongRange: longRangeSecurityKeysFromEnvironment("PIPHI_ZWAVE_LR"),
      logConfig: {
        enabled: process.env.LOG_LEVEL !== "silent",
        level: normalizeLogLevel(process.env.LOG_LEVEL),
        logToFile: false,
      },
    }) as unknown as DriverLike;
    this.driver = driver;
    this.bindEvents(driver);
    try {
      await driver.start();
    } catch (error) {
      this.driver = undefined;
      this.lifecycle = "degraded";
      this.lastErrorCode = errorCode(error);
      this.emit("driver.failed", { error_code: this.lastErrorCode });
      await safeDestroy(driver);
      this.scheduleRecovery();
      throw error;
    }
  }

  async stop(): Promise<void> {
    this.stopRequested = true;
    if (this.recoveryTimer) clearTimeout(this.recoveryTimer);
    this.recoveryTimer = undefined;
    const driver = this.driver;
    if (!driver) {
      this.lifecycle = "stopped";
      return;
    }
    this.lifecycle = "stopping";
    this.driver = undefined;
    await safeDestroy(driver);
    this.driverReady = false;
    this.controllerReady = false;
    this.lifecycle = "stopped";
    this.emit("driver.destroyed", {});
  }

  async execute(command: DriverCommand): Promise<Record<string, unknown>> {
    if (command.name === "reconnect_driver") {
      await this.stop();
      this.reconnectCount += 1;
      await this.start();
      return { reconnected: true, reconnect_count: this.reconnectCount };
    }
    const driver = this.requireDriver();
    if (command.name === "refresh_controller_information") {
      return { refreshed: true, snapshot: this.snapshot() };
    }
    const node = getNode(driver, command.nodeId);
    if (command.name === "ping_node") {
      return { node_id: command.nodeId, reachable: await node.ping(true) };
    }
    if (command.name === "request_node_interview") {
      await node.interview();
      return { node_id: command.nodeId, interview_requested: true };
    }
    if (command.name === "refresh_node_values") {
      await node.refreshValues();
      return { node_id: command.nodeId, values_refreshed: true };
    }
    if (command.name === "set_value") {
      const resolved = resolveWritableValue(node, command.valueId, command.value);
      const result = await node.setValue(resolved.valueId, resolved.value);
      return {
        node_id: command.nodeId,
        value_id: command.valueId,
        accepted_value: sanitizeZWaveValue(resolved.value),
        result: sanitizeZWaveValue(result),
      };
    }
    throw new Error("unsupported_driver_command");
  }

  snapshot(): DriverSnapshot {
    const nodes = this.driver ? [...this.driver.controller.nodes].map(([, node]) => node) : [];
    return {
      lifecycle: this.lifecycle,
      driverReady: this.driverReady,
      controllerReady: this.controllerReady,
      controllerPathSuffix: redactControllerPath(this.config.controller_path),
      driverVersion: libVersion,
      ...(this.driver?.controller.homeId != null
        ? { homeIdSuffix: this.driver.controller.homeId.toString(16).padStart(8, "0").slice(-4) }
        : {}),
      ...(this.driver?.controller.ownNodeId != null
        ? { controllerNodeId: this.driver.controller.ownNodeId }
        : {}),
      nodeCount: nodes.length,
      readyNodeCount: nodes.filter((node) => node.ready === true || node.isReady === true).length,
      sleepingNodeCount: nodes.filter((node) => node.status === NodeStatus.Asleep || String(node.status).toLowerCase() === "asleep").length,
      deadNodeCount: nodes.filter((node) => node.status === NodeStatus.Dead || String(node.status).toLowerCase() === "dead").length,
      reconnectCount: this.reconnectCount,
      ...(this.lastEventAt ? { lastEventAt: this.lastEventAt } : {}),
      ...(this.lastErrorCode ? { lastErrorCode: this.lastErrorCode } : {}),
    };
  }

  nodesSnapshot(): ZWaveNodeSnapshot[] {
    if (!this.driver) return [];
    return [...this.driver.controller.nodes]
      .map(([, node]) => nodeSnapshot(node))
      .sort((left, right) => left.node_id - right.node_id);
  }

  private bindEvents(driver: DriverLike): void {
    driver.on("driver ready", () => {
      this.driverReady = true;
      this.controllerReady = true;
      this.lifecycle = "ready";
      this.recoveryBackoffMs = 1_000;
      this.emit("driver.ready", this.controllerSummary(driver));
    });
    driver.on("all nodes ready", () => this.emit("nodes.all_ready", this.controllerSummary(driver)));
    driver.on("error", (error: unknown) => {
      this.lifecycle = "degraded";
      this.lastErrorCode = errorCode(error);
      this.emit("driver.failed", { error_code: this.lastErrorCode });
      this.scheduleRecovery();
    });
    for (const eventName of NODE_EVENTS) {
      driver.on(`node ${eventName}`, (...args: unknown[]) => {
        const node = args[0] as Record<string, unknown>;
        this.publish(normalizeNodeEvent(eventName, node, args.slice(1)));
      });
    }
  }

  private controllerSummary(driver: DriverLike): Record<string, unknown> {
    return sanitizeZWaveValue({
      controller_node_id: driver.controller.ownNodeId,
      home_id_suffix: driver.controller.homeId?.toString(16).padStart(8, "0").slice(-4),
      node_count: [...driver.controller.nodes].length,
    }) as Record<string, unknown>;
  }

  private emit(eventType: string, payload: Record<string, unknown>): void {
    this.publish({
      schema_version: "piphi.zwave.event.v1",
      occurred_at: new Date().toISOString(),
      event_type: eventType,
      source: "zwave-js",
      payload,
    });
  }

  private publish(event: Omit<ZWaveTransportEvent, "sequence">): void {
    this.lastEventAt = event.occurred_at;
    this.onEvent(event);
  }

  private requireDriver(): DriverLike {
    if (!this.driver || !this.driverReady) throw new Error("driver_not_ready");
    return this.driver;
  }

  private scheduleRecovery(): void {
    if (this.stopRequested || this.recoveryTimer) return;
    const delay = this.recoveryBackoffMs;
    this.recoveryBackoffMs = Math.min(delay * 2, 30_000);
    this.recoveryTimer = setTimeout(() => {
      this.recoveryTimer = undefined;
      void this.recover().catch(() => this.scheduleRecovery());
    }, delay);
    this.recoveryTimer.unref?.();
  }

  private async recover(): Promise<void> {
    if (this.stopRequested) return;
    const failedDriver = this.driver;
    this.driver = undefined;
    this.driverReady = false;
    this.controllerReady = false;
    if (failedDriver) await safeDestroy(failedDriver);
    this.reconnectCount += 1;
    await this.start();
    this.emit("driver.recovered", { reconnect_count: this.reconnectCount });
  }
}

export function createZWaveJsDriverSession(options: {
  config: DeviceConfig;
  onEvent: (event: Omit<ZWaveTransportEvent, "sequence">) => void;
}): DriverSession {
  validateControllerPath(options.config.controller_path);
  return new ZWaveJsDriverSession(options.config, options.onEvent);
}

export function validateControllerPath(controllerPath: string): void {
  const value = String(controllerPath ?? "").trim();
  if (!value || value.includes("\0") || value.includes("..")) {
    throw new Error("controller_path is invalid");
  }
  const explicitlyAllowed = (process.env.PIPHI_ZWAVE_ALLOWED_CONTROLLER_PATHS ?? "")
    .split(",").map((item) => item.trim()).filter(Boolean);
  const stable = value.startsWith("/dev/serial/by-id/") || value.startsWith("/dev/serial/by-path/");
  const unstableAllowed = process.env.PIPHI_ZWAVE_ALLOW_UNSTABLE_TTY === "true"
    && /^\/dev\/tty(?:ACM|USB)\d+$/.test(value);
  if (!stable && !unstableAllowed && !explicitlyAllowed.includes(value)) {
    throw new Error("controller_path must be stable or explicitly allow-listed");
  }
}

export function redactControllerPath(controllerPath: string): string {
  const token = controllerPath.split("/").filter(Boolean).at(-1) ?? "unknown";
  return token.length <= 12 ? token : token.slice(-12);
}

function getNode(driver: DriverLike, nodeId: number): NodeLike {
  if (!Number.isInteger(nodeId) || nodeId < 1 || nodeId > 4_000) throw new Error("invalid_node_id");
  const node = [...driver.controller.nodes].find(([id]) => id === nodeId)?.[1];
  if (!node) throw new Error("unknown_node_id");
  return node;
}

function nodeSnapshot(node: NodeLike): ZWaveNodeSnapshot {
  const values = node.getDefinedValueIDs().flatMap((valueId) => {
    const metadata = node.getValueMetadata(valueId as Record<string, unknown>);
    if (isSensitiveValue(valueId, metadata) || metadata.type === "buffer") return [];
    const readable = metadata.readable !== false;
    const writeable = metadata.writeable === true;
    if (!readable && !writeable) return [];
    const timestamp = node.getValueTimestamp(valueId as Record<string, unknown>);
    const states = metadata.states && typeof metadata.states === "object"
      ? Object.fromEntries(Object.entries(metadata.states as Record<string, unknown>).map(([key, value]) => [key, String(value)]))
      : undefined;
    return [{
      id: toPublicValueId(valueId),
      label: String(metadata.label ?? valueId.propertyName ?? valueId.property),
      ...(valueId.propertyName ? { property_name: valueId.propertyName } : {}),
      ...(valueId.propertyKeyName ? { property_key_name: valueId.propertyKeyName } : {}),
      value: readable ? sanitizeZWaveValue(node.getValue(valueId as Record<string, unknown>)) : null,
      ...(typeof timestamp === "number" ? { updated_at: new Date(timestamp).toISOString() } : {}),
      metadata: {
        type: String(metadata.type ?? "any"),
        readable,
        writeable,
        stateful: metadata.stateful !== false,
        ...(typeof metadata.unit === "string" ? { unit: metadata.unit } : {}),
        ...(typeof metadata.min === "number" ? { min: metadata.min } : {}),
        ...(typeof metadata.max === "number" ? { max: metadata.max } : {}),
        ...(typeof metadata.steps === "number" ? { step: metadata.steps } : {}),
        ...(states ? { states } : {}),
        ...(typeof metadata.description === "string" ? { description: metadata.description } : {}),
      },
    }];
  });
  return {
    node_id: node.id,
    ...(node.name ? { name: node.name } : {}),
    ...(node.location ? { location: node.location } : {}),
    ...(typeof node.manufacturerId === "number" ? { manufacturer_id: node.manufacturerId } : {}),
    ...(typeof node.productType === "number" ? { product_type: node.productType } : {}),
    ...(typeof node.productId === "number" ? { product_id: node.productId } : {}),
    ...(node.firmwareVersion ? { firmware_version: node.firmwareVersion } : {}),
    status: String(node.status ?? "unknown").toLowerCase(),
    ready: node.ready === true || node.isReady === true,
    ...(node.lastSeen instanceof Date ? { last_seen_at: node.lastSeen.toISOString() } : {}),
    values,
  };
}

export function isSensitiveValue(
  valueId: {
    property: string | number;
    propertyKey?: string | number;
    propertyName?: string;
    propertyKeyName?: string;
  },
  metadata: Record<string, unknown>,
): boolean {
  if (metadata.secret === true) return true;
  return [
    valueId.property,
    valueId.propertyKey,
    valueId.propertyName,
    valueId.propertyKeyName,
    metadata.label,
    metadata.description,
  ].some((value) => SENSITIVE_VALUE_TOKEN.test(String(value ?? "")));
}

function toPublicValueId(valueId: {
  commandClass: number;
  endpoint?: number;
  property: string | number;
  propertyKey?: string | number;
}): ZWaveValueId {
  return {
    command_class: valueId.commandClass,
    endpoint: valueId.endpoint ?? 0,
    property: valueId.property,
    ...(valueId.propertyKey != null ? { property_key: valueId.propertyKey } : {}),
  };
}

function resolveWritableValue(
  node: NodeLike,
  requested: ZWaveValueId,
  value: unknown,
): { valueId: Record<string, unknown>; value: unknown } {
  const valueId = node.getDefinedValueIDs().find((candidate) => (
    candidate.commandClass === requested.command_class
    && (candidate.endpoint ?? 0) === requested.endpoint
    && candidate.property === requested.property
    && candidate.propertyKey === requested.property_key
  ));
  if (!valueId) throw new Error("unknown_value_id");
  const metadata = node.getValueMetadata(valueId as Record<string, unknown>);
  if (isSensitiveValue(valueId, metadata) || metadata.writeable !== true || metadata.type === "buffer") {
    throw new Error("value_is_not_safely_writeable");
  }
  const normalized = validateValueAgainstMetadata(value, metadata);
  return { valueId: valueId as Record<string, unknown>, value: normalized };
}

function validateValueAgainstMetadata(value: unknown, metadata: Record<string, unknown>): unknown {
  const type = String(metadata.type ?? "any");
  if (type === "boolean") {
    if (typeof value !== "boolean") throw new Error("value_must_be_boolean");
    return value;
  }
  if (type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("value_must_be_finite_number");
    if (typeof metadata.min === "number" && value < metadata.min) throw new Error("value_below_minimum");
    if (typeof metadata.max === "number" && value > metadata.max) throw new Error("value_above_maximum");
    if (metadata.states && typeof metadata.states === "object" && metadata.allowManualEntry === false) {
      if (!(String(value) in metadata.states)) throw new Error("value_is_not_an_allowed_state");
    }
    return value;
  }
  if (type === "string" || type === "color") {
    if (typeof value !== "string") throw new Error("value_must_be_string");
    if (typeof metadata.minLength === "number" && value.length < metadata.minLength) throw new Error("value_is_too_short");
    if (typeof metadata.maxLength === "number" && value.length > metadata.maxLength) throw new Error("value_is_too_long");
    return value;
  }
  throw new Error("value_type_is_not_supported_for_write");
}

function securityKeysFromEnvironment(prefix: string): Record<string, Uint8Array> | undefined {
  const pairs = [
    ["S2_AccessControl", `${prefix}_S2_ACCESS_CONTROL_KEY`],
    ["S2_Authenticated", `${prefix}_S2_AUTHENTICATED_KEY`],
    ["S2_Unauthenticated", `${prefix}_S2_UNAUTHENTICATED_KEY`],
    ["S0_Legacy", `${prefix}_S0_LEGACY_KEY`],
  ] as const;
  const values = Object.fromEntries(pairs.flatMap(([name, env]) => {
    const key = parseSecurityKey(process.env[env], env);
    return key ? [[name, key]] : [];
  }));
  return Object.keys(values).length ? values : undefined;
}

function longRangeSecurityKeysFromEnvironment(prefix: string): Record<string, Uint8Array> | undefined {
  const values = Object.fromEntries([
    ["S2_AccessControl", parseSecurityKey(process.env[`${prefix}_S2_ACCESS_CONTROL_KEY`], `${prefix}_S2_ACCESS_CONTROL_KEY`)],
    ["S2_Authenticated", parseSecurityKey(process.env[`${prefix}_S2_AUTHENTICATED_KEY`], `${prefix}_S2_AUTHENTICATED_KEY`)],
  ].filter((entry): entry is [string, Uint8Array] => entry[1] != null));
  return Object.keys(values).length ? values : undefined;
}

function parseSecurityKey(value: string | undefined, name: string): Uint8Array | undefined {
  if (!value) return undefined;
  if (!/^[0-9a-fA-F]{32}$/.test(value)) throw new Error(`${name} must contain exactly 32 hexadecimal characters`);
  return Uint8Array.from(Buffer.from(value, "hex"));
}

function normalizeLogLevel(level: string | undefined): "error" | "warn" | "info" | "verbose" | "debug" | "silly" {
  return ["error", "warn", "info", "verbose", "debug", "silly"].includes(level ?? "")
    ? level as "error" | "warn" | "info" | "verbose" | "debug" | "silly"
    : "info";
}

function errorCode(error: unknown): string {
  if (error && typeof error === "object" && "code" in error) return String(error.code);
  return error instanceof Error ? error.name : "unknown_error";
}

async function safeDestroy(driver: DriverLike): Promise<void> {
  try {
    await driver.destroy();
  } catch {
    // The serial port may already be unavailable; shutdown remains idempotent.
  }
}
