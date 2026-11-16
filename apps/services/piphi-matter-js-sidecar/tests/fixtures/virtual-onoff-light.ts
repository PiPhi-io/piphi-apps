import { DeviceTypeId, Endpoint, ServerNode, VendorId } from "@matter/main";
import { OnOffLightDevice } from "@matter/main/devices/on-off-light";

const node = await ServerNode.create({
  id: "piphi-e2e-onoff-light",
  network: { port: 0 },
  commissioning: { passcode: 20202021, discriminator: 3840 },
  productDescription: {
    name: "PiPhi E2E Light",
    deviceType: DeviceTypeId(OnOffLightDevice.deviceType),
  },
  basicInformation: {
    vendorName: "PiPhi Test",
    vendorId: VendorId(0xfff1),
    productName: "PiPhi Virtual OnOff Light",
    productLabel: "PiPhi Virtual OnOff Light",
    nodeLabel: "PiPhi Virtual OnOff Light",
    productId: 0x8000,
    serialNumber: "piphi-e2e-light-1",
    uniqueId: "piphi-e2e-light-unique-1",
    hardwareVersion: 1,
    hardwareVersionString: "1.0",
    softwareVersion: 1,
    softwareVersionString: "1.0.0",
  },
});

const light = new Endpoint(OnOffLightDevice, { id: "onoff" });
await node.add(light);
light.events.onOff.onOff$Changed.on((value) => send({ type: "onoff", value }));
node.lifecycle.decommissioned.on(() => send({ type: "decommissioned" }));
await node.start();

const { qrPairingCode, manualPairingCode } = node.state.commissioning.pairingCodes;
send({
  type: "ready",
  qrPairingCode,
  manualPairingCode,
  endpoint: Number(light.number),
});

let stopping = false;
async function stop(): Promise<void> {
  if (stopping) return;
  stopping = true;
  await node.close();
}
process.once("SIGINT", () => void stop());
process.once("SIGTERM", () => void stop());

function send(message: Record<string, unknown>): void {
  if (process.send) process.send(message);
  else console.log(JSON.stringify(message));
}
