import type { JsonObject, SidecarEventPage, SidecarSnapshot } from "./types.js";

export class SidecarRequestError extends Error {
  constructor(readonly status: number) {
    super(`Matter sidecar request failed with HTTP ${status}`);
    this.name = "SidecarRequestError";
  }
}

export class SidecarClient {
  constructor(private readonly baseUrl: string, private readonly token: string) {}

  async snapshot(): Promise<SidecarSnapshot> {
    const value = await this.request("/v1/matter/snapshot") as Partial<SidecarSnapshot>;
    if (value.schema_version !== "piphi.matter.snapshot.v1"
      || typeof value.stream_id !== "string"
      || !Number.isInteger(value.latest_sequence)
      || !value.controller
      || typeof value.controller.identity_hash !== "string"
      || !value.controller.identity_hash
      || !Array.isArray(value.nodes)) {
      throw new Error("Invalid Matter sidecar snapshot contract");
    }
    return value as SidecarSnapshot;
  }

  async events(after: number): Promise<SidecarEventPage> {
    const value = await this.request(`/v1/matter/events?after=${after}&limit=500`) as Partial<SidecarEventPage>;
    if (value.schema_version !== "piphi.matter.events.v1"
      || typeof value.stream_id !== "string"
      || !Number.isInteger(value.latest_sequence)
      || !Number.isInteger(value.next_cursor)
      || typeof value.gap !== "boolean"
      || !Array.isArray(value.events)) {
      throw new Error("Invalid Matter sidecar event contract");
    }
    return value as SidecarEventPage;
  }

  async command(nodeId: string, endpointId: number, command: string): Promise<JsonObject> {
    return await this.request("/v1/commands/invoke", {
      method: "POST",
      body: JSON.stringify({ node_id: nodeId, endpoint_id: endpointId, command, args: {} }),
    }) as JsonObject;
  }

  async commissionables(timeoutSeconds: number): Promise<unknown[]> {
    const value = await this.request(`/v1/discovery/commissionables?timeout_seconds=${timeoutSeconds}`);
    if (!Array.isArray(value)) throw new Error("Invalid Matter commissionables response");
    return value;
  }

  async commissionOnNetwork(setupPayload: string): Promise<JsonObject> {
    return await this.request("/v1/commission/code", {
      method: "POST",
      body: JSON.stringify({ setup_payload: setupPayload, network_only: true }),
    }) as JsonObject;
  }

  async provisionWifi(setupPayload: string, ssid: string, credentials: string): Promise<JsonObject> {
    return await this.request("/v1/commission/wifi", {
      method: "POST",
      body: JSON.stringify({ setup_payload: setupPayload, ssid, credentials }),
    }) as JsonObject;
  }

  async decommissionNode(nodeId: string): Promise<JsonObject> {
    return await this.request(`/v1/nodes/${encodeURIComponent(nodeId)}/decommission`, {
      method: "POST",
      body: JSON.stringify({ confirm_node_id: nodeId }),
    }) as JsonObject;
  }

  async preflight(): Promise<JsonObject> {
    const value = await this.request("/v1/preflight");
    if (!value || typeof value !== "object" || Array.isArray(value)
      || (value as JsonObject).schema_version !== "piphi.matter.preflight.v1") {
      throw new Error("Invalid Matter sidecar preflight contract");
    }
    return value as JsonObject;
  }

  async quiesceForBackup(): Promise<JsonObject> {
    return await this.request("/v1/admin/backup/quiesce", {
      method: "POST",
      body: JSON.stringify({ confirmation: "quiesce-matter-controller" }),
    }) as JsonObject;
  }

  async resumeAfterBackup(): Promise<JsonObject> {
    return await this.request("/v1/admin/backup/resume", { method: "POST", body: "{}" }) as JsonObject;
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers: { ...this.headers(), ...init.headers } });
    if (!response.ok) throw new SidecarRequestError(response.status);
    return response.status === 204 ? null : response.json();
  }

  private headers(): Record<string, string> {
    return { "content-type": "application/json", ...(this.token ? { authorization: `Bearer ${this.token}` } : {}) };
  }
}
