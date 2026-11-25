const SENSITIVE_KEY = /(token|secret|password|credential|dataset|setup[_-]?payload|private[_-]?key|certificate|fabric|ssid)/i;

export function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key,
      SENSITIVE_KEY.test(key) ? "[REDACTED]" : redact(item),
    ]));
  }
  return value;
}

export function publicErrorCode(error: unknown): string {
  if (error && typeof error === "object" && "code" in error) {
    const code = String(error.code);
    if (/^[a-z0-9_]{1,80}$/i.test(code) && !SENSITIVE_KEY.test(code)) return code.toLowerCase();
  }
  return "internal_error";
}
