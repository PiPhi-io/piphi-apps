declare module "@alcalzone/proper-lockfile" {
  export interface LockOptions {
    realpath?: boolean;
    stale?: number;
    update?: number;
    retries?: number;
    lockfilePath?: string;
  }

  export function lock(path: string, options?: LockOptions): Promise<() => Promise<void>>;
}
