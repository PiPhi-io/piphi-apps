export type JsonObject = Record<string, unknown>;

export interface MatterNodeSnapshot {
  nodeId: string;
  available: boolean;
  dateCommissioned?: string;
  matterVersion?: string;
  attributes: JsonObject;
}

export interface MatterCommissionable {
  instanceName?: string;
  vendorId?: number;
  productId?: number;
  deviceType?: number;
  longDiscriminator?: number;
  commissioningMode?: number;
  addresses: string[];
}

export interface MatterEndpoint {
  nodeId: string;
  endpointId: number;
  name: string;
  vendorName?: string;
  productName?: string;
  deviceTypes: string[];
  capabilities: string[];
  commandBindings: string[];
  state: JsonObject;
  metadata: JsonObject;
}

export interface ConfiguredEndpoint {
  node_id: string;
  endpoint_id: number;
  alias?: string;
  enabled: boolean;
  preferred_source: "matter";
}

export interface MatterEvent {
  id: string;
  type: string;
  timestamp: string;
  node_id?: string;
  endpoint_id?: number;
  payload: JsonObject;
}

export interface MatterBackend {
  readonly connected: boolean;
  diagnostics(): JsonObject;
  start(): Promise<void>;
  quiesce(): Promise<void>;
  resume(): Promise<void>;
  stop(): Promise<void>;
  listNodes(): Promise<MatterNodeSnapshot[]>;
  getNode(nodeId: string): Promise<MatterNodeSnapshot>;
  discoverCommissionables(timeoutSeconds: number): Promise<MatterCommissionable[]>;
  commissionWithCode(setupCode: string, networkOnly?: boolean, options?: {
    wifiCredentialsId?: string;
    discoveryTimeoutSeconds?: number;
    timeoutMs?: number;
  }): Promise<MatterNodeSnapshot>;
  setWifiCredentials(ssid: string, credentials: string, id?: string): Promise<void>;
  setThreadDataset(dataset: string): Promise<void>;
  clearWifiCredentials(id?: string): Promise<void>;
  clearTemporaryWifiCredentials(prefix: string): Promise<number>;
  clearThreadDataset(): Promise<void>;
  removeNode(nodeId: string): Promise<void>;
  invoke(nodeId: string, endpointId: number, command: string, args: JsonObject): Promise<unknown>;
  onEvent(listener: (event: MatterEvent) => void): () => void;
}
