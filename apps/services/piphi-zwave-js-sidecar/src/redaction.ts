const SENSITIVE_KEY = /(s0|s2|security|network.?key|credential|token|secret|password|dsk|pin|raw.?frame|nvm|backup.?data|private)/i;

export function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [
      key,
      SENSITIVE_KEY.test(key) ? "[redacted]" : redact(item),
    ]));
  }
  return value;
}

export function publicErrorCode(error: unknown): string {
  const candidate = error && typeof error === "object" && "code" in error
    ? String((error as { code?: unknown }).code)
    : error instanceof Error ? error.message : "internal_error";
  const normalized = candidate.toLowerCase().replace(/[^a-z0-9_]+/g, "_").slice(0, 80);
  return normalized && !SENSITIVE_KEY.test(normalized) ? normalized : "zwave_operation_rejected";
}
