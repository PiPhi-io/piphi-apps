import type { JsonObject, MatterEndpoint, MatterNodeSnapshot } from "./types.js";

const clusters = {
  onOff: 6,
  levelControl: 8,
  descriptor: 29,
  powerSource: 47,
  booleanState: 69,
  illuminance: 1024,
  temperature: 1026,
  occupancy: 1030,
  humidity: 1029,
} as const;

const deviceTypeNames: Record<number, string> = {
  0x0015: "contact_sensor",
  0x0100: "on_off_light",
  0x0101: "dimmable_light",
  0x0106: "light_sensor",
  0x0107: "occupancy_sensor",
  0x010a: "on_off_plug_in_unit",
  0x010d: "dimmable_plug_in_unit",
  0x0302: "temperature_sensor",
  0x0307: "humidity_sensor",
};

function key(endpoint: number, cluster: number, attribute: number): string {
  return `${endpoint}/${cluster}/${attribute}`;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function deviceTypes(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const result = new Set<string>();
  for (const item of value) {
    const id = typeof item === "number"
      ? item
      : item && typeof item === "object" && "deviceType" in item
        ? Number((item as { deviceType: unknown }).deviceType)
        : Number.NaN;
    if (!Number.isFinite(id)) continue;
    result.add(deviceTypeNames[id] ?? `matter_device_0x${id.toString(16).padStart(4, "0")}`);
  }
  return [...result].sort();
}

function endpointNumbers(attributes: JsonObject): number[] {
  const endpoints = new Set<number>();
  for (const path of Object.keys(attributes)) {
    const endpoint = Number(path.split("/", 1)[0]);
    if (Number.isInteger(endpoint) && endpoint > 0) endpoints.add(endpoint);
  }
  return [...endpoints].sort((a, b) => a - b);
}

function hasCluster(attributes: JsonObject, endpoint: number, cluster: number): boolean {
  const serverList = attributes[key(endpoint, clusters.descriptor, 1)];
  return (Array.isArray(serverList) && serverList.some((value) => Number(value) === cluster))
    || Object.keys(attributes).some((path) => path.startsWith(`${endpoint}/${cluster}/`));
}

export function normalizeNode(node: MatterNodeSnapshot): MatterEndpoint[] {
  const vendorName = asNonEmptyString(node.attributes["0/40/1"]);
  const productName = asNonEmptyString(node.attributes["0/40/3"]);
  const nodeLabel = asNonEmptyString(node.attributes["0/40/5"]);
  return endpointNumbers(node.attributes).map((endpointId) => {
    const types = deviceTypes(node.attributes[key(endpointId, clusters.descriptor, 0)]);
    const state: JsonObject = { connected: node.available };
    const capabilities = new Set<string>(["connected"]);
    const commands = new Set<string>(["refresh"]);

    if (hasCluster(node.attributes, endpointId, clusters.onOff)) {
      const value = node.attributes[key(endpointId, clusters.onOff, 0)];
      if (typeof value === "boolean") state.switch_on = value;
      capabilities.add("switch_on");
      commands.add("turn_on");
      commands.add("turn_off");
      commands.add("toggle");
    }
    if (hasCluster(node.attributes, endpointId, clusters.levelControl)) {
      const value = numberValue(node.attributes[key(endpointId, clusters.levelControl, 0)]);
      if (value !== undefined) state.brightness_percent = Math.round((value / 254) * 1000) / 10;
      capabilities.add("brightness_percent");
    }
    addCentiCapability(node.attributes, state, capabilities, endpointId, clusters.temperature, "temperature_c");
    addCentiCapability(node.attributes, state, capabilities, endpointId, clusters.humidity, "humidity_percent");
    const occupancy = numberValue(node.attributes[key(endpointId, clusters.occupancy, 0)]);
    if (occupancy !== undefined) {
      state.occupancy_detected = (occupancy & 1) === 1;
      capabilities.add("occupancy_detected");
    }
    const illuminance = numberValue(node.attributes[key(endpointId, clusters.illuminance, 0)]);
    if (illuminance !== undefined) {
      state.illuminance_raw = illuminance;
      capabilities.add("illuminance_raw");
    }
    const booleanState = node.attributes[key(endpointId, clusters.booleanState, 0)];
    if (typeof booleanState === "boolean" && types.includes("contact_sensor")) {
      state.contact_open = booleanState;
      capabilities.add("contact_open");
    }
    const batteryHalfPercent = numberValue(node.attributes[key(endpointId, clusters.powerSource, 12)]);
    if (batteryHalfPercent !== undefined) {
      state.battery_percent = batteryHalfPercent / 2;
      capabilities.add("battery_percent");
    }

    return {
      nodeId: node.nodeId,
      endpointId,
      name: nodeLabel ?? productName ?? `Matter ${node.nodeId}/${endpointId}`,
      ...(vendorName === undefined ? {} : { vendorName }),
      ...(productName === undefined ? {} : { productName }),
      deviceTypes: types,
      capabilities: [...capabilities].sort(),
      commandBindings: [...commands].sort(),
      state,
      metadata: {
        node_id: node.nodeId,
        endpoint_id: endpointId,
        matter_version: node.matterVersion ?? null,
        vendor_id: node.attributes["0/40/2"] ?? null,
        product_id: node.attributes["0/40/4"] ?? null,
      },
    };
  });
}

function addCentiCapability(
  attributes: JsonObject,
  state: JsonObject,
  capabilities: Set<string>,
  endpoint: number,
  cluster: number,
  capability: string,
): void {
  const value = numberValue(attributes[key(endpoint, cluster, 0)]);
  if (value === undefined) return;
  state[capability] = value / 100;
  capabilities.add(capability);
}

function asNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export const supportedCommands = ["refresh", "toggle", "turn_off", "turn_on"] as const;
export type SupportedCommand = typeof supportedCommands[number];

export function isSupportedCommand(value: string): value is SupportedCommand {
  return supportedCommands.includes(value as SupportedCommand);
}
