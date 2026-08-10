/**
 * API client — talks to the Hookrelay backend.
 *
 * All requests use SAME-ORIGIN relative paths (e.g. `/api/v1/...`) and rely
 * on the Next.js rewrite in next.config.mjs to proxy to the backend origin
 * (HOOKRELAY_API_ORIGIN / NEXT_PUBLIC_API_BASE_URL, default localhost:8000).
 * This keeps the browser free of CORS and lets one build work in dev and in
 * production (standalone output served behind the same origin).
 *
 * NEXT_PUBLIC_API_BASE_URL is still honoured as an escape hatch for setups
 * that serve the API from a separate origin with CORS enabled.
 */
const API_BASE_URL: string =
  (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined) ?? "";

/** Standard API error with status code for UI handling. */
export class ApiError extends Error {
  status: number;
  code?: string;
  retryable: boolean;
  retryAfterSeconds?: number;

  constructor(
    status: number,
    message: string,
    options: { code?: string; retryable?: boolean; retryAfterSeconds?: number } = {}
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = options.code;
    this.retryable = options.retryable ?? (status === 408 || status === 429 || status >= 500);
    this.retryAfterSeconds = options.retryAfterSeconds;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    let code: string | undefined;
    try {
      const body = await res.json();
      if (body.detail && typeof body.detail === "string") detail = body.detail;
      else if (body.detail && typeof body.detail === "object") {
        detail = (body.detail as any).message ?? detail;
        code = (body.detail as any).code;
      }
    } catch {
      // non-JSON error body — keep the generic message
    }
    const retryHeader = res.headers.get("Retry-After");
    const parsedRetry = retryHeader ? Number(retryHeader) : undefined;
    throw new ApiError(res.status, detail, {
      code,
      retryAfterSeconds: Number.isFinite(parsedRetry) ? parsedRetry : undefined,
    });
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Transformation {
  transform_id: string;
  name: string;
  filters: string[];
  created_at: string;
  updated_at: string;
}

export interface CreateTransformationRequest {
  name: string;
  filters: string[];
}

export interface UpdateTransformationRequest {
  name?: string;
  filters?: string[];
}

export interface Destination {
  destination_id: string;
  bin_id: string;
  url: string;
  transform_id: string | null;
  signing_config: SigningConfig;
  headers: Record<string, string>;
  retry_policy: RetryPolicy;
  enabled: boolean;
  weight: number;
  delivery_mode: "broadcast" | "round_robin" | "weighted";
  delivered_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
}

export interface SigningConfig {
  algorithm?: "svix" | "hookdeck" | "github" | "custom";
  key?: string;
  header_name?: string;
  timestamp_header?: string;
  [key: string]: any;
}

export interface RetryPolicy {
  max_attempts?: number;
  base_delay_ms?: number;
  max_delay_ms?: number;
  backoff_multiplier?: number;
  retry_on?: number[];
  [key: string]: any;
}

export interface CreateDestinationRequest {
  bin_id: string;
  url: string;
  transform_id?: string;
  signing_config?: SigningConfig;
  headers?: Record<string, string>;
  retry_policy?: RetryPolicy;
  enabled?: boolean;
  weight?: number;
  delivery_mode?: "broadcast" | "round_robin" | "weighted";
}

export interface UpdateDestinationRequest {
  url?: string;
  transform_id?: string | null;
  signing_config?: SigningConfig;
  headers?: Record<string, string>;
  retry_policy?: RetryPolicy;
  enabled?: boolean;
  weight?: number;
  delivery_mode?: "broadcast" | "round_robin" | "weighted";
}

export interface CaptureBin {
  bin_id: string;
  /** Deprecated alias for backward compatibility; the API returns `description`. */
  name?: string;
  description?: string | null;
  url: string;
  created_at: string;
  request_count: number;
}

export interface InsightsEndpoint {
  endpoint_id: string;
  deliveries: number;
  success_rate: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  top_failure_reason: string | null;
}

export interface InsightsEndpointsResponse {
  window: string;
  endpoints: InsightsEndpoint[];
}

export interface InsightsTimeseriesBucket {
  bucket: string;
  value: number | null;
  delivered?: number;
  failed?: number;
}

export interface InsightsTimeseriesResponse {
  metric: string;
  window: string;
  bucket: string;
  buckets: InsightsTimeseriesBucket[];
}

// ---------------------------------------------------------------------------
// Transformations API
// ---------------------------------------------------------------------------

export async function listTransformations(): Promise<Transformation[]> {
  return request<Transformation[]>("/api/v1/transformations");
}

export async function getTransformation(
  transformId: string
): Promise<Transformation> {
  return request<Transformation>(`/api/v1/transformations/${transformId}`);
}

export async function createTransformation(
  body: CreateTransformationRequest
): Promise<Transformation> {
  return request<Transformation>("/api/v1/transformations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateTransformation(
  transformId: string,
  body: UpdateTransformationRequest
): Promise<Transformation> {
  return request<Transformation>(`/api/v1/transformations/${transformId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteTransformation(
  transformId: string
): Promise<void> {
  await request<void>(`/api/v1/transformations/${transformId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Destinations API
// ---------------------------------------------------------------------------

export async function listDestinations(
  binId?: string
): Promise<Destination[]> {
  const path = binId ? `/api/v1/destinations?bin_id=${encodeURIComponent(binId)}` : "/api/v1/destinations";
  return request<Destination[]>(path);
}

export async function getDestination(
  destinationId: string
): Promise<Destination> {
  return request<Destination>(`/api/v1/destinations/${destinationId}`);
}

export async function createDestination(
  body: CreateDestinationRequest
): Promise<Destination> {
  return request<Destination>("/api/v1/destinations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updateDestination(
  destinationId: string,
  body: UpdateDestinationRequest
): Promise<Destination> {
  return request<Destination>(`/api/v1/destinations/${destinationId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function deleteDestination(
  destinationId: string
): Promise<void> {
  await request<void>(`/api/v1/destinations/${destinationId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// Capture Bins API
// ---------------------------------------------------------------------------

export async function listBins(): Promise<CaptureBin[]> {
  return request<CaptureBin[]>("/api/bins");
}

// ---------------------------------------------------------------------------
// Insights API
// ---------------------------------------------------------------------------

export async function getInsightsEndpoints(
  window: "15m" | "1h" | "24h" | "7d" = "24h"
): Promise<InsightsEndpointsResponse> {
  return request<InsightsEndpointsResponse>(
    `/api/insights/endpoints?window=${window}`
  );
}

export async function getInsightsTimeseries(
  metric: "deliveries" | "success_rate" | "latency_p95" = "deliveries",
  window: "15m" | "1h" | "24h" | "7d" = "24h",
  bucket: "hourly" | "daily" = "hourly"
): Promise<InsightsTimeseriesResponse> {
  return request<InsightsTimeseriesResponse>(
    `/api/insights/timeseries?metric=${metric}&window=${window}&bucket=${bucket}`
  );
}

// ---------------------------------------------------------------------------
// Built-in transformation functions (for UI chips)
// ---------------------------------------------------------------------------

export const BUILTIN_FUNCTIONS = [
  { name: "uppercase", label: "uppercase", description: "Convert to uppercase" },
  { name: "lowercase", label: "lowercase", description: "Convert to lowercase" },
  { name: "timestamp", label: "timestamp", description: "Current ISO-8601 timestamp" },
  { name: "uuid", label: "uuid", description: "Generate UUID v4" },
  { name: "hash", label: "hash", description: "SHA-256 hex digest" },
  { name: "mask_secrets", label: "mask_secrets", description: "Mask sensitive values" },
] as const;

export type BuiltinFunction = (typeof BUILTIN_FUNCTIONS)[number]["name"];

// ---------------------------------------------------------------------------
// Client-side LIVE preview of transformations
//
// Mirrors src/hookrelay/transforms/engine.py so the builder can render
// "what you see is what you get" output without a round-trip. The backend
// engine remains the source of truth at delivery time; this is a preview
// helper only and must behave identically for the documented sub-language.
// ---------------------------------------------------------------------------

function splitPath(path: string): string[] {
  return path
    .trim()
    .replace(/^\.+/, "")
    .split(".")
    .filter((p) => p.length > 0);
}

function getPath(payload: Record<string, unknown>, path: string): unknown {
  let node: unknown = payload;
  for (const key of splitPath(path)) {
    if (typeof node !== "object" || node === null || !(key in node)) return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function setPath(
  payload: Record<string, unknown>,
  path: string,
  value: unknown
): Record<string, unknown> {
  const work = { ...payload };
  const keys = splitPath(path);
  if (keys.length === 0) return work;
  let node: Record<string, unknown> = work;
  for (const key of keys.slice(0, -1)) {
    const child = node[key];
    if (typeof child !== "object" || child === null || Array.isArray(child)) {
      node[key] = {};
    }
    node = node[key] as Record<string, unknown>;
  }
  node[keys[keys.length - 1]] = value;
  return work;
}

function delPath(
  payload: Record<string, unknown>,
  path: string
): Record<string, unknown> {
  const work = { ...payload };
  const keys = splitPath(path);
  if (keys.length === 0) return work;
  let node: Record<string, unknown> = work;
  for (const key of keys.slice(0, -1)) {
    if (typeof node[key] !== "object" || node[key] === null || Array.isArray(node[key])) {
      return work;
    }
    node = node[key] as Record<string, unknown>;
  }
  delete node[keys[keys.length - 1]];
  return work;
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}

function maskValue(value: unknown): string {
  if (typeof value === "string" && value.startsWith("«redacted")) return "***";
  const text = stringify(value);
  if (text.length === 0) return "***";
  if (text.length <= 4) return "***";
  return text.slice(0, 2) + "*".repeat(text.length - 4) + text.slice(-2);
}

async function sha256Hex(input: string): Promise<string> {
  // Real SHA-256 via WebCrypto — matches the backend's hashlib.sha256.
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function applyBuiltin(
  payload: Record<string, unknown>,
  fn: string,
  targetPath: string
): Promise<Record<string, unknown>> {
  const work = { ...payload };
  const current = getPath(work, targetPath);
  let value: unknown;
  switch (fn) {
    case "uppercase":
      value = stringify(current).toUpperCase();
      break;
    case "lowercase":
      value = stringify(current).toLowerCase();
      break;
    case "timestamp":
      value = new Date().toISOString();
      break;
    case "uuid":
      value = crypto.randomUUID();
      break;
    case "hash":
      value = await sha256Hex(stringify(current));
      break;
    case "mask_secrets":
      value = maskValue(current);
      break;
    default:
      throw new Error(`unknown builtin: ${fn}`);
  }
  return setPath(work, targetPath, value);
}

function parseScalar(token: string): unknown {
  const t = token.trim();
  if (t === "true") return true;
  if (t === "false") return false;
  if (t === "null") return null;
  if (t === "now") return new Date().toISOString();
  try {
    return JSON.parse(t);
  } catch {
    // fall through to bare-word handling below
  }
  const quoted = t.match(/^"([\s\S]*)"$/);
  if (quoted) return quoted[1];
  return t;
}

function isPathLike(token: string): boolean {
  return /^\.?[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$/.test(token);
}

/** Apply a single JQ-style statement to a payload (mirrors engine._parse_statement). */
async function applyStatement(
  payload: Record<string, unknown>,
  stmt: string
): Promise<Record<string, unknown>> {
  const s = stmt.trim();
  if (!s || s === ".") return payload;

  // del(.field)
  let m = s.match(/^del\s*\(\s*(\.?[A-Za-z0-9_.]+)\s*\)$/);
  if (m) return delPath(payload, m[1]);

  // .field |= builtin
  m = s.match(/^\.?([A-Za-z0-9_.]+)\s*\|\=\s*([A-Za-z0-9_]+)\s*$/);
  if (m) return applyBuiltin(payload, m[2], m[1]);
  // .field :: type (type conversion)
  m = s.match(/^\.?([A-Za-z0-9_.]+)\s*::\s*([A-Za-z0-9_]+)\s*$/);
  if (m) {
    const work = { ...payload };
    const keys = splitPath(m[1]);
    if (keys.length === 0) return work;
    let node: Record<string, unknown> = work;
    for (const key of keys.slice(0, -1)) {
      if (typeof node[key] !== "object" || node[key] === null) return work;
      node = node[key] as Record<string, unknown>;
    }
    const last = keys[keys.length - 1];
    if (last in node) {
      const raw = node[last];
      const t = m[2].toLowerCase();
      if (t === "int" || t === "integer") node[last] = parseInt(String(raw), 10);
      else if (t === "str" || t === "string") node[last] = stringify(raw);
      else if (t === "float" || t === "number") node[last] = parseFloat(String(raw));
      else if (t === "bool" || t === "boolean") {
        if (typeof raw === "string") node[last] = ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
        else node[last] = Boolean(raw);
      } else throw new Error(`unsupported target type: ${m[2]}`);
    }
    return work;
  }

  // .field = <value|builtin|source-path>
  m = s.match(/^\.?([A-Za-z0-9_.]+)\s*=\s*(.+)$/);
  if (m) {
    const path = m[1];
    const rhs = m[2].trim();
    if (["uppercase", "lowercase", "timestamp", "uuid", "hash", "mask_secrets"].includes(rhs)) {
      return applyBuiltin(payload, rhs, path);
    }
    if (isPathLike(rhs) && rhs !== path) {
      // rename: .new = .old — missing source yields null (mirrors engine)
      const value = getPath(payload, rhs) ?? null;
      const moved = delPath(payload, rhs);
      return setPath(moved, path, value);
    }
    return setPath(payload, path, parseScalar(rhs));
  }

  // Unknown statement — mirror engine behaviour: treat as literal field set.
  return payload;
}

/**
 * Live preview: apply an ordered list of JQ-style filter strings to a JSON
 * payload and return the transformed result. Pure function, no network.
 * Async only because the ``hash`` builtin uses WebCrypto (SHA-256).
 */
export async function previewTransformation(
  filters: string[],
  payload: Record<string, unknown>
): Promise<Record<string, unknown>> {
  let work = { ...payload };
  for (const expression of filters || []) {
    // Split on pipes but NOT on |= (update-assign operator) — mirrors engine.
    const parts: string[] = [];
    let current = "";
    let i = 0;
    while (i < expression.length) {
      if (expression[i] === "|" && expression[i + 1] === "=") {
        current += "|=";
        i += 2;
      } else if (expression[i] === "|") {
        parts.push(current);
        current = "";
        i += 1;
      } else {
        current += expression[i];
        i += 1;
      }
    }
    parts.push(current);
    for (const stmt of parts) {
      const s = stmt.trim();
      if (!s || s === ".") continue;
      work = await applyStatement(work, s);
    }
  }
  return work;
}