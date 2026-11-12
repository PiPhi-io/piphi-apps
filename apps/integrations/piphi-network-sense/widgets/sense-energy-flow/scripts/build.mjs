import { copyFile, mkdir, readdir, rm } from "node:fs/promises";

const source = new URL("../src/", import.meta.url);
const output = new URL("../dist/", import.meta.url);

await rm(output, { recursive:true, force:true });
await mkdir(output, { recursive:true });
for (const entry of await readdir(source, { withFileTypes:true })) {
  if (entry.isFile() && entry.name.endsWith(".js")) {
    await copyFile(new URL(entry.name, source), new URL(entry.name, output));
  }
}
