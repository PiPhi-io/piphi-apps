import { buildCoreEventPayload, buildRuntimeAuthHeaders } from "piphi-runtime-kit-node";
import type { ProjectedEntity } from "./types.js";

export interface CoreDeliverySettings {
  endpoint?: string;
  eventEndpoint?: string;
  containerId?: string;
  token?: string;
  configId?: string;
}

export class CoreClient {
  constructor(private readonly settings: CoreDeliverySettings) {}

  async telemetry(entity: ProjectedEntity): Promise<"delivered" | "not_configured"> {
    if (!this.settings.endpoint || !this.settings.containerId) return "not_configured";
    const response = await fetch(this.settings.endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...buildRuntimeAuthHeaders({
          containerId: this.settings.containerId,
          internalToken: this.settings.token ?? null,
        }),
      },
      body: JSON.stringify({ device_id: entity.device_id, timestamp: new Date().toISOString(), metrics: entity.state }),
    });
    if (!response.ok) throw new Error(`PiPhi Core telemetry delivery failed with HTTP ${response.status}`);
    return "delivered";
  }

  async stateChanged(entity: ProjectedEntity, previousState: ProjectedEntity["state"]): Promise<"delivered" | "not_configured"> {
    if (!this.settings.eventEndpoint || !this.settings.containerId) return "not_configured";
    const event = buildCoreEventPayload({
      eventType: "device.state_changed",
      integrationId: "piphi-network-matter-integration",
      configId: this.settings.configId ?? "matter-controller",
      containerId: this.settings.containerId,
      deviceId: entity.device_id,
      source: "integration",
      severity: "info",
      payload: { entity_id: entity.id, previous: previousState, current: entity.state },
    });
    const response = await fetch(this.settings.eventEndpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...buildRuntimeAuthHeaders({
          containerId: this.settings.containerId,
          internalToken: this.settings.token ?? null,
        }),
      },
      body: JSON.stringify(event),
    });
    if (!response.ok) throw new Error(`PiPhi Core event delivery failed with HTTP ${response.status}`);
    return "delivered";
  }
}
