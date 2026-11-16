import { createApp } from "./app.js";
import { MatterJsBackend } from "./matterjs-backend.js";
import { MatterSidecarService } from "./service.js";
import { loadSettings } from "./settings.js";

const settings = loadSettings();
const backend = new MatterJsBackend(settings);
const service = new MatterSidecarService(backend, settings);
const app = createApp(service);

await app.listen({ host: settings.apiHost, port: settings.apiPort });

let stopping = false;
async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  await app.close();
}

process.once("SIGINT", () => void stop());
process.once("SIGTERM", () => void stop());
