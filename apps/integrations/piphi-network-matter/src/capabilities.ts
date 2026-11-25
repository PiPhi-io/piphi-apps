import type { JsonObject, ProjectedEntity, SidecarNode } from "./types.js";

const COMMANDS = ["refresh", "turn_on", "turn_off", "toggle"] as const;
export type Command = typeof COMMANDS[number];

export function isCommand(value: string): value is Command {
  return COMMANDS.includes(value as Command);
}

export function stableEntityId(controllerIdentityHash: string, nodeId: string, endpointId: number): string {
  return `matter:${controllerIdentityHash}:${encodeURIComponent(nodeId)}:${endpointId}`;
}

export function projectNodes(
  nodes: SidecarNode[],
  controllerIdentityHash: string,
  aliasFor: (nodeId: string, endpointId: number) => string | undefined,
): ProjectedEntity[] {
  return nodes.flatMap((node) => endpointNumbers(node.attributes).map((endpointId) => {
    const state: JsonObject & { connected: boolean; switch_on?: boolean } = { connected: node.available };
    const capabilities = new Set(["connected"]);
    const commands = new Set<string>(["refresh"]);
    const onOff = node.attributes[`${endpointId}/6/0`];
    if (hasCluster(node.attributes, endpointId, 6)) {
      if (typeof onOff === "boolean") state.switch_on = onOff;
      capabilities.add("switch_on");
      commands.add("turn_on"); commands.add("turn_off"); commands.add("toggle");
    }
    const level = finiteNumber(node.attributes[`${endpointId}/8/0`]);
    if (level !== undefined && hasCluster(node.attributes, endpointId, 8)) {
      state.brightness_percent = Math.round((level / 254) * 1000) / 10;
      capabilities.add("brightness_percent");
    }
    addCenti(node.attributes, state, capabilities, endpointId, 1026, "temperature_c");
    addCenti(node.attributes, state, capabilities, endpointId, 1029, "humidity_percent");
    const battery = finiteNumber(node.attributes[`${endpointId}/47/12`]);
    if (battery !== undefined) { state.battery_percent = battery / 2; capabilities.add("battery_percent"); }
    const occupancy = finiteNumber(node.attributes[`${endpointId}/1030/0`]);
    if (occupancy !== undefined) { state.occupancy_detected = (occupancy & 1) === 1; capabilities.add("occupancy_detected"); }
    const illuminance = finiteNumber(node.attributes[`${endpointId}/1024/0`]);
    if (illuminance !== undefined) { state.illuminance_raw = illuminance; capabilities.add("illuminance_raw"); }
    const booleanState = node.attributes[`${endpointId}/69/0`];
    if (typeof booleanState === "boolean" && hasDeviceType(node.attributes, endpointId, 0x0015)) {
      state.contact_open = booleanState; capabilities.add("contact_open");
    }
    const nodeName = nonEmptyString(node.attributes["0/40/5"])
      ?? nonEmptyString(node.attributes["0/40/3"])
      ?? `Matter ${node.node_id}/${endpointId}`;
    return {
      id: stableEntityId(controllerIdentityHash, node.node_id, endpointId),
      device_id: `matter:${controllerIdentityHash}:${encodeURIComponent(node.node_id)}`,
      name: aliasFor(node.node_id, endpointId) ?? nodeName,
      device_class: deviceClass(capabilities),
      capabilities: [...capabilities].sort(),
      available_commands: [...commands].sort(),
      state,
      metadata: { controller_identity_hash: controllerIdentityHash, node_id: node.node_id, endpoint_id: endpointId, source: "matter_sidecar" as const },
    };
  }));
}

export const projectOnOffNodes = projectNodes;

function endpointNumbers(attributes: JsonObject): number[] {
  const endpoints = new Set<number>();
  for (const path of Object.keys(attributes)) {
    const endpoint = Number(path.split("/", 1)[0]);
    if (Number.isInteger(endpoint) && endpoint > 0) endpoints.add(endpoint);
  }
  return [...endpoints].sort((left, right) => left - right);
}

function hasCluster(attributes: JsonObject, endpointId: number, clusterId: number): boolean {
  const servers = attributes[`${endpointId}/29/1`];
  return (Array.isArray(servers) && servers.some((value) => Number(value) === clusterId))
    || Object.hasOwn(attributes, `${endpointId}/${clusterId}/0`);
}

function hasDeviceType(attributes: JsonObject, endpointId: number, expected: number): boolean {
  const types = attributes[`${endpointId}/29/0`];
  return Array.isArray(types) && types.some((item) => Number(
    item && typeof item === "object" && "deviceType" in item ? item.deviceType : item,
  ) === expected);
}

function addCenti(attributes: JsonObject, state: JsonObject, capabilities: Set<string>, endpointId: number, clusterId: number, name: string): void {
  const value = finiteNumber(attributes[`${endpointId}/${clusterId}/0`]);
  if (value !== undefined) { state[name] = value / 100; capabilities.add(name); }
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function deviceClass(capabilities: Set<string>): ProjectedEntity["device_class"] {
  if (capabilities.has("switch_on")) return capabilities.has("brightness_percent") ? "light" : "switch";
  if (capabilities.has("contact_open")) return "binary_sensor";
  if (capabilities.size > 1) return "sensor";
  return "matter_device";
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
