export type StreamErrorKind =
  | "network"
  | "http_4xx"
  | "http_5xx"
  | "rate_limit"
  | "unknown";

export type StreamErrorInfo = {
  kind: StreamErrorKind;
  message: string;
  retryable: boolean;
};

export class StreamHttpError extends Error {
  readonly status: number;

  constructor(status: number, detail: string, label = "Stream API") {
    super(`${label} ${status}: ${detail}`);
    this.name = "StreamHttpError";
    this.status = status;
  }
}

function classifyStatus(status: number, message: string): StreamErrorInfo {
  if (status === 429) {
    return { kind: "rate_limit", message, retryable: true };
  }
  if (status >= 500) {
    return { kind: "http_5xx", message, retryable: true };
  }
  if (status >= 400) {
    return { kind: "http_4xx", message, retryable: false };
  }
  return { kind: "unknown", message, retryable: false };
}

function messageFromUnknown(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  if (error instanceof Event) return `Stream connection ${error.type || "failed"}`;
  if (typeof error === "string") return error;
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

export function classifyStreamError(error: unknown): StreamErrorInfo {
  if (error instanceof StreamHttpError) {
    return classifyStatus(error.status, error.message);
  }

  if (error && typeof error === "object" && "status" in error) {
    const status = Number((error as { status?: unknown }).status);
    if (Number.isFinite(status)) {
      return classifyStatus(status, messageFromUnknown(error));
    }
  }

  const message = messageFromUnknown(error);
  const statusMatch = message.match(/\b(?:API|Stream API)\s+(\d{3})\b/);
  if (statusMatch) {
    return classifyStatus(Number(statusMatch[1]), message);
  }

  if (
    error instanceof TypeError ||
    error instanceof Event ||
    /failed to fetch|networkerror|load failed/i.test(message)
  ) {
    return { kind: "network", message, retryable: true };
  }

  return { kind: "unknown", message, retryable: false };
}
