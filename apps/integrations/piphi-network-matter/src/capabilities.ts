import type { JsonObject, ProjectedEntity, SidecarNode } from "./types.js";

const COMMANDS = ["turn_on", "turn_off", "toggle"] as const;
export type Command = typeof COMMANDS[number];

export function isCommand(value: string): value is Command {
  return COMMANDS.includes(value as Command);
}

export function stableEntityId(controllerIdentityHash: string, nodeId: string, endpointId: number): string {
  return `matter:${controllerIdentityHash}:${encodeURIComponent(nodeId)}:${endpointId}`;
}

export function projectOnOffNodes(
  nodes: SidecarNode[],
  controllerIdentityHash: string,
  aliasFor: (nodeId: string, endpointId: number) => string | undefined,
): ProjectedEntity[] {
  return nodes.flatMap((node) => endpointNumbers(node.attributes).flatMap((endpointId) => {
    if (!hasOnOffCluster(node.attributes, endpointId)) return [];
    const switchOn = node.attributes[`${endpointId}/6/0`];
    const nodeName = nonEmptyString(node.attributes["0/40/5"])
      ?? nonEmptyString(node.attributes["0/40/3"])
      ?? `Matter ${node.node_id}/${endpointId}`;
    return [{
      id: stableEntityId(controllerIdentityHash, node.node_id, endpointId),
      device_id: `matter:${controllerIdentityHash}:${encodeURIComponent(node.node_id)}`,
      name: aliasFor(node.node_id, endpointId) ?? nodeName,
      device_class: "switch" as const,
      capabilities: ["connected", "switch_on"],
      available_commands: [...COMMANDS],
      state: {
        connected: node.available,
        ...(typeof switchOn === "boolean" ? { switch_on: switchOn } : {}),
      },
      metadata: {
        controller_identity_hash: controllerIdentityHash,
        node_id: node.node_id,
        endpoint_id: endpointId,
        source: "matter_sidecar" as const,
      },
    }];
  }));
}

function endpointNumbers(attributes: JsonObject): number[] {
  const endpoints = new Set<number>();
  for (const path of Object.keys(attributes)) {
    const endpoint = Number(path.split("/", 1)[0]);
    if (Number.isInteger(endpoint) && endpoint > 0) endpoints.add(endpoint);
  }
  return [...endpoints].sort((left, right) => left - right);
}

function hasOnOffCluster(attributes: JsonObject, endpointId: number): boolean {
  const servers = attributes[`${endpointId}/29/1`];
  return (Array.isArray(servers) && servers.some((value) => Number(value) === 6))
    || Object.hasOwn(attributes, `${endpointId}/6/0`);
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
