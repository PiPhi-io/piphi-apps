import { lock } from "@alcalzone/proper-lockfile";
import { chmod, mkdir } from "node:fs/promises";
import { join } from "node:path";

export type StorageLeaseRelease = () => Promise<void>;

export async function acquireStorageLease(storageDir: string): Promise<StorageLeaseRelease> {
  await mkdir(storageDir, { recursive: true, mode: 0o700 });
  await chmod(storageDir, 0o700);
  try {
    return await lock(storageDir, {
      realpath: false,
      retries: 0,
      stale: 30_000,
      update: 10_000,
      lockfilePath: join(storageDir, ".piphi-controller.lock"),
    });
  } catch (error) {
    const code = error && typeof error === "object" && "code" in error
      ? String(error.code)
      : "unknown";
    throw new Error(
      `Matter controller storage is already in use or cannot be locked (${code}). Refusing to start a duplicate controller.`,
      { cause: error },
    );
  }
}
