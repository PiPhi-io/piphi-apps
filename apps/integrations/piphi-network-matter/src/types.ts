export type JsonObject = Record<string, unknown>;

export interface SidecarNode {
  node_id: string;
  available: boolean;
  date_commissioned?: string | null;
  matter_version?: string | null;
  attributes: JsonObject;
}

export interface SidecarSnapshot {
  schema_version: "piphi.matter.snapshot.v1";
  stream_id: string;
  latest_sequence: number;
  dropped_event_count: number;
  controller: {
    connected: boolean;
    identity_hash: string;
    sdk_version?: string | null;
    schema_version?: number | null;
  };
  nodes: SidecarNode[];
}

export interface SidecarEvent {
  sequence: number;
  type: string;
  timestamp: string;
  node_id?: string;
  endpoint_id?: number;
  payload: JsonObject;
}

export interface SidecarEventPage {
  schema_version: "piphi.matter.events.v1";
  stream_id: string;
  first_sequence: number;
  latest_sequence: number;
  next_cursor: number;
  dropped_event_count: number;
  gap: boolean;
  events: SidecarEvent[];
}

export interface ProjectedEntity {
  id: string;
  device_id: string;
  name: string;
  device_class: "switch";
  capabilities: string[];
  available_commands: string[];
  state: { connected: boolean; switch_on?: boolean };
  metadata: { controller_identity_hash: string; node_id: string; endpoint_id: number; source: "matter_sidecar" };
}

export interface EndpointConfig {
  controller_identity_hash: string;
  node_id: string;
  endpoint_id: number;
  alias?: string;
  enabled: boolean;
}
