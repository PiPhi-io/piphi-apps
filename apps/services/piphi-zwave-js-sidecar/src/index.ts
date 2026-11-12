import { createApp } from "./app.js";
import { runtimePort } from "./settings.js";

const app = createApp();
const port = runtimePort();

await app.listen({ host: "0.0.0.0", port });
