import {
  AutomationRegistry,
  FileAutomationIdempotencyStore,
  buildLocalEventRecord,
  createRuntimeStarter,
  scheduleEventDelivery,
  shutdownBackgroundTasks,
  type RuntimeRegistry,
} from "piphi-runtime-kit-node";

import { commands } from "./contract.js";
import { createZWaveJsDriverSession } from "./driver-session.js";
import { integrationId, integrationName, integrationVersion } from "./settings.js";
import { BoundedEventBuffer, SerialCommandQueue } from "./transport.js";
import type {
  DeviceConfig,
  DeviceEntry,
  DeviceState,
  DriverCommand,
  DriverSession,
  DriverSessionFactory,
  ZWaveTransportEvent,
} from "./types.js";

export const starter = createRuntimeStarter({
  integrationId,
  integrationName,
  version: integrationVersion,
  maxRecentEvents: 250,
});

export const runtime = starter.runtime;
export const registry = starter.registry as unknown as RuntimeRegistry<
  DeviceState,
  DeviceEntry,
  Record<string, unknown>
>;
export const telemetry = starter.telemetryClient;
export const configSync = starter.configSync;
export const automations = new AutomationRegistry({
  idempotencyStore: new FileAutomationIdempotencyStore(
    process.env.PIPHI_AUTOMATION_LEDGER_DIR ?? "./data/automation-actions",
  ),
});

let sessionFactory: DriverSessionFactory = createZWaveJsDriverSession;
let activeSession: DriverSession | undefined;
let activeConfigId: string | undefined;
let eventBuffer = new BoundedEventBuffer();
let commandQueue = new SerialCommandQueue();

export function setDriverSessionFactory(factory: DriverSessionFactory): void {
  if (activeSession) throw new Error("cannot replace driver factory while a controller is active");
  sessionFactory = factory;
}

export function resetDriverSessionFactory(): void {
  setDriverSessionFactory(createZWaveJsDriverSession);
}

export function buildEntry(config: DeviceConfig): DeviceEntry {
  const configId = String(config.configId ?? config.id);
  return {
    configId,
    deviceId: String(config.deviceId ?? config.id),
    containerId: config.containerId,
    integrationId: config.integrationId ?? integrationId,
    controllerPath: config.controller_path,
    alias: config.alias,
    config,
  };
}

export async function applyConfig(config: DeviceConfig): Promise<void> {
  validateConfig(config);
  const entry = buildEntry(config);
  if (activeConfigId && activeConfigId !== entry.configId) {
    throw new Error("only_one_controller_configuration_is_supported");
  }

  const nextEventBuffer = new BoundedEventBuffer(config.event_queue_capacity ?? 1_000);
  const nextCommandQueue = new SerialCommandQueue(config.command_queue_capacity ?? 100);
  const session = sessionFactory({
    config,
    onEvent: (event) => receiveZWaveEvent(entry, event),
  });
  const previousSession = activeSession;
  if (previousSession) await previousSession.stop();

  eventBuffer = nextEventBuffer;
  commandQueue = nextCommandQueue;
  activeSession = session;
  activeConfigId = entry.configId;
  registry.set(entry.configId, entry);
  updateControllerState(entry);

  try {
    await session.start();
  } catch (error) {
    updateControllerState(entry);
    throw error;
  }

  updateControllerState(entry);
  appendRuntimeEvent("runtime.config.applied", entry, {
    controller_path_suffix: session.snapshot().controllerPathSuffix,
    alias: config.alias ?? null,
  });
}

export async function removeConfig(configId: string): Promise<boolean> {
  const entry = registry.get(configId);
  if (!entry) return false;
  if (activeConfigId === configId && activeSession) await activeSession.stop();
  activeSession = undefined;
  activeConfigId = undefined;
  registry.remove(configId);
  appendRuntimeEvent("runtime.config.removed", entry, {
    controller_path_suffix: controllerPathSuffix(entry.controllerPath),
    alias: entry.alias ?? null,
  });
  return true;
}

export async function executeDriverCommand(
  configId: string,
  commandName: keyof typeof commands,
  args: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const entry = registry.get(configId);
  if (!entry || activeConfigId !== configId || !activeSession) throw new Error("controller_not_configured");
  const command = parseDriverCommand(commandName, args);
  const result = await commandQueue.submit(() => activeSession!.execute(command));
  updateControllerState(entry);
  appendRuntimeEvent("runtime.command.completed", entry, {
    command: commandName,
    node_id: "nodeId" in command ? command.nodeId : null,
  });
  return result;
}

export function readZWaveEvents(after = 0, limit = 100) {
  return eventBuffer.read(after, limit);
}

export function controllerDiagnostics(): Record<string, unknown> {
  return {
    snapshot: activeSession?.snapshot() ?? null,
    event_queue: {
      depth: eventBuffer.depth,
      capacity: eventBuffer.capacity,
      dropped: eventBuffer.dropped,
      latest_sequence: eventBuffer.lastSequence,
    },
    command_queue: {
      depth: commandQueue.depth,
      capacity: commandQueue.capacity,
    },
  };
}

export async function shutdownRuntime(): Promise<void> {
  if (activeSession) await activeSession.stop();
  activeSession = undefined;
  activeConfigId = undefined;
  await shutdownBackgroundTasks(runtime.processState, { gracePeriodMs: 3_000 });
}

export function appendRuntimeEvent(
  eventType: string,
  entry: Partial<DeviceEntry> & { deviceId: string; configId: string },
  payload: Record<string, unknown>,
) {
  return registry.appendEvent(
    buildLocalEventRecord({
      eventType,
      deviceId: entry.deviceId,
      configId: entry.configId,
      containerId: entry.containerId ?? runtime.auth.containerId ?? null,
      integrationId: entry.integrationId ?? integrationId,
      source: integrationId,
      severity: "info",
      payload,
    }),
  );
}

function receiveZWaveEvent(
  entry: DeviceEntry,
  event: Omit<ZWaveTransportEvent, "sequence">,
): void {
  const buffered = eventBuffer.append(event);
  appendRuntimeEvent("zwave.transport.event", entry, { event: buffered });
  updateControllerState(entry);
  if (runtime.auth.containerId && runtime.auth.internalToken) {
    void scheduleEventDelivery({
      processState: runtime.processState,
      eventClient: starter.eventClient,
      authContext: runtime.auth,
      eventType: "zwave.transport.event",
      device: entry,
      payload: { event: buffered },
      source: integrationId,
      ts: event.occurred_at,
    }).catch(() => undefined);
  }
}

function updateControllerState(entry: DeviceEntry): void {
  const snapshot = activeSession?.snapshot();
  const state: DeviceState = {
    connected: snapshot?.lifecycle === "ready",
    driver_ready: snapshot?.driverReady ?? false,
    controller_ready: snapshot?.controllerReady ?? false,
    controller_path_suffix: snapshot?.controllerPathSuffix ?? controllerPathSuffix(entry.controllerPath),
    lifecycle: snapshot?.lifecycle ?? "stopped",
    node_count: snapshot?.nodeCount ?? 0,
    ready_node_count: snapshot?.readyNodeCount ?? 0,
    sleeping_node_count: snapshot?.sleepingNodeCount ?? 0,
    dead_node_count: snapshot?.deadNodeCount ?? 0,
    event_sequence: eventBuffer.lastSequence,
    event_queue_depth: eventBuffer.depth,
    dropped_event_count: eventBuffer.dropped,
    command_queue_depth: commandQueue.depth,
    command_queue_capacity: commandQueue.capacity,
    last_event_at: snapshot?.lastEventAt ?? null,
    last_error_code: snapshot?.lastErrorCode ?? null,
    alias: entry.alias,
  };
  registry.updateState(entry.configId, state, entry.deviceId);
}

function parseDriverCommand(commandName: keyof typeof commands, args: Record<string, unknown>): DriverCommand {
  if (commandName === "refresh_controller_information") return { name: commandName };
  if (commandName === "reconnect_driver") return { name: commandName };
  const nodeId = Number(args.node_id ?? args.nodeId);
  if (!Number.isInteger(nodeId) || nodeId < 1 || nodeId > 4_000) throw new Error("node_id must be an integer between 1 and 4000");
  return { name: commandName, nodeId } as DriverCommand;
}

function validateConfig(config: DeviceConfig): void {
  if (!config || typeof config !== "object") throw new Error("configuration is required");
  if (!String(config.id ?? "").trim()) throw new Error("id is required");
  if (!String(config.controller_path ?? "").trim()) throw new Error("controller_path is required");
}

function controllerPathSuffix(path: string): string {
  const name = path.split("/").filter(Boolean).at(-1) ?? "unknown";
  return name.length > 12 ? name.slice(-12) : name;
}

for (const commandName of Object.keys(commands) as Array<keyof typeof commands>) {
  automations.action(commandName, {
    label: commands[commandName].description,
  })(async (request) => {
    const target = request.target && typeof request.target === "object"
      ? request.target as Record<string, unknown>
      : {};
    const deviceId = String(request.deviceId ?? target.device_id ?? "zwave-js-service");
    const configId = String(request.configId ?? target.config_id ?? deviceId);
    const result = await executeDriverCommand(configId, commandName, request.args ?? {});
    return { command: commandName, device_id: deviceId, config_id: configId, ...result };
  });
}
