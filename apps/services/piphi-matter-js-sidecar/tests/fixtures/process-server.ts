import { createApp } from "../../src/app.js";
import { MatterSidecarService } from "../../src/service.js";
import type { MatterSettings } from "../../src/settings.js";
import type { JsonObject } from "../../src/types.js";
import { FakeMatterBackend, sampleNode } from "../fake-backend.js";

class ProcessFixtureBackend extends FakeMatterBackend {
  constructor() {
    const node = sampleNode("node-17");
    node.attributes["0/40/3"] = "Desk plug";
    node.attributes["0/40/5"] = "Desk plug";
    node.attributes["1/29/1"] = [6];
    node.attributes["1/6/0"] = process.env.TEST_SWITCH_ON === "true";
    super([node]);
  }

  override async invoke(nodeId: string, endpointId: number, command: string, args: JsonObject): Promise<unknown> {
    const result = await super.invoke(nodeId, endpointId, command, args);
    const node = this.nodes.find((candidate) => candidate.nodeId === nodeId);
    if (!node) throw new Error(`Node ${nodeId} not found`);
    const path = `${endpointId}/6/0`;
    if (command === "turn_on") node.attributes[path] = true;
    else if (command === "turn_off") node.attributes[path] = false;
    else if (command === "toggle") node.attributes[path] = !node.attributes[path];
    this.emit("device.state_changed");
    return result;
  }

  setSwitchOn(value: boolean): void {
    this.nodes[0]!.attributes["1/6/0"] = value;
  }
}

const port = Number(process.env.PORT ?? 18710);
const storageDir = process.env.MATTER_STORAGE_DIR ?? "/tmp/piphi-matter-process-fixture";
const settings: MatterSettings = {
  apiHost: "127.0.0.1",
  apiPort: port,
  backendHost: "127.0.0.1",
  backendPort: 5580,
  backendUrl: "ws://127.0.0.1:5580/ws",
  storageDir,
  manageBackend: false,
  enableBle: false,
  dclOffline: true,
  logManagedServer: false,
};
const backend = new ProcessFixtureBackend();
const service = new MatterSidecarService(backend, settings);
const app = createApp(service);

app.post<{ Body: { switch_on?: boolean; event_count?: number } }>("/test/burst", async (request) => {
  backend.setSwitchOn(request.body.switch_on ?? false);
  const count = Math.max(0, Math.min(Number(request.body.event_count ?? 0), 2_000));
  for (let index = 0; index < count; index += 1) backend.emit("device.state_changed");
  return { ok: true, emitted: count };
});

await app.listen({ host: "127.0.0.1", port });

let stopping = false;
async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  await app.close();
}
process.once("SIGINT", () => void stop());
process.once("SIGTERM", () => void stop());
