export const integrationId = "piphi-zwave-js-sidecar";
export const integrationName = "Piphi Zwave Js Sidecar";
export const integrationVersion = "0.1.1";
export const projectKind = "sidecar";
export const projectPreset = "sidecar-worker";
export const projectDomain = "sidecar-service";
export const defaultPort = 4211;

export function runtimePort(): number {
  const raw = process.env.PORT;
  if (raw === undefined) return defaultPort;
  if (!/^\d+$/.test(raw)) throw new RangeError("PORT must be an integer between 1 and 65535.");
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new RangeError("PORT must be an integer between 1 and 65535.");
  }
  return value;
}
