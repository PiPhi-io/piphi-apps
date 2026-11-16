import dbus from "@jellybrick/dbus-next";

export interface BlePreflightResult {
  status: "pass" | "fail";
  adapter: string;
  transport: "bluez_dbus";
  reason?: "system_bus_unavailable" | "bluez_unavailable" | "adapter_missing" | "adapter_powered_off";
}

type ManagedObjects = Record<string, Record<string, Record<string, { value?: unknown }>>>;
export interface BluezBus {
  getProxyObject(name: string, path: string): Promise<{
    getInterface(name: string): { GetManagedObjects(): Promise<ManagedObjects> };
  }>;
  disconnect(): void;
  on?(event: "error", listener: (error: unknown) => void): unknown;
}

export function evaluateBluezObjects(objects: ManagedObjects, adapter = "hci0"): BlePreflightResult {
  const path = Object.keys(objects).find((candidate) => candidate.endsWith(`/${adapter}`));
  if (!path || !objects[path]?.["org.bluez.Adapter1"]) {
    return { status: "fail", adapter, transport: "bluez_dbus", reason: "adapter_missing" };
  }
  if (objects[path]["org.bluez.Adapter1"].Powered?.value !== true) {
    return { status: "fail", adapter, transport: "bluez_dbus", reason: "adapter_powered_off" };
  }
  return { status: "pass", adapter, transport: "bluez_dbus" };
}

export async function checkBluezAdapter(
  adapter = "hci0",
  timeoutMs = 2_000,
  busFactory: () => BluezBus = () => dbus.systemBus(),
): Promise<BlePreflightResult> {
  let bus: BluezBus | undefined;
  try {
    bus = busFactory();
    // dbus-next can emit a late socket error while disconnecting after a completed call.
    // Keep that transport detail inside this bounded preflight instead of crashing the service.
    bus.on?.("error", () => undefined);
  } catch {
    return { status: "fail", adapter, transport: "bluez_dbus", reason: "system_bus_unavailable" };
  }
  let timeout: NodeJS.Timeout | undefined;
  try {
    const objects = await Promise.race([
      bus.getProxyObject("org.bluez", "/").then((proxy) => (
        proxy.getInterface("org.freedesktop.DBus.ObjectManager").GetManagedObjects()
      )) as Promise<ManagedObjects>,
      new Promise<never>((_resolve, reject) => {
        timeout = setTimeout(() => reject(new Error("timeout")), timeoutMs);
      }),
    ]);
    return evaluateBluezObjects(objects, adapter);
  } catch {
    return { status: "fail", adapter, transport: "bluez_dbus", reason: "bluez_unavailable" };
  } finally {
    if (timeout) clearTimeout(timeout);
    bus.disconnect();
  }
}
