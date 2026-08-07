export type ActionStatus = "PROPOSED" | "APPROVED" | "REJECTED" | "COMPLETED";
export type ActionOperation = "APPROVE" | "REJECT" | "COMPLETE";

export type OperationsAction = {
  action_id: string;
  alert_fingerprint: string;
  shipment_id: string;
  action_type: string;
  alert_type: string;
  alert_severity: string;
  status: ActionStatus;
  approval_required: string;
  approved_by: string | null;
  approved_at: string | null;
  completed_at: string | null;
  created_date: string;
};

export type RiskStatus = "OPEN" | "RESOLVED";

export type OperationsRisk = {
  alert_fingerprint: string;
  shipment_id: string;
  alert_type: string;
  alert_grain: string;
  alert_dimension: string;
  severity: string;
  status: RiskStatus;
  first_detected_date: string;
  last_detected_date: string;
  resolved_date: string | null;
  metric_name: string;
  metric_value: string;
  threshold_value: string;
  as_of_date: string;
};

type QueueResponse = {
  schema_version: "operations-api.v1";
  items: OperationsAction[];
  next_token: string | null;
};

type RiskResponse = {
  schema_version: "operations-api.v1";
  items: OperationsRisk[];
  next_token: string | null;
};

const tokenKey = "glap.internal.operations.access_token";

export function operationsApiUrl() {
  return (process.env.NEXT_PUBLIC_GLAP_OPERATIONS_API_URL ?? "").replace(/\/$/, "");
}

export function internalOperationsEnabled() {
  return operationsApiUrl().startsWith("https://");
}

export function readOperationsToken() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(tokenKey) ?? "";
}

function sydneyDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Australia/Sydney", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  if (!internalOperationsEnabled()) throw new Error("Internal Operations API is not configured");
  if (!token) throw new Error("Authenticated internal session is required");
  const response = await fetch(`${operationsApiUrl()}${path}`, {
    ...init,
    cache: "no-store",
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...init?.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || body.error || "Operations request failed");
  return body as T;
}

export async function loadActionQueue(token: string, status?: ActionStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}&limit=100` : "?limit=100";
  return request<QueueResponse>(`/v1/actions${query}`, token);
}

export async function loadRiskHotspots(token: string, status?: RiskStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}&limit=100` : "?limit=100";
  return request<RiskResponse>(`/v1/risks${query}`, token);
}

export async function mutateAction(
  token: string, actionId: string, operation: ActionOperation, reason: string,
) {
  return request<{ schema_version: string; action: { action_status: ActionStatus } }>(
    `/v1/actions/${encodeURIComponent(actionId)}/events`, token, {
      method: "POST",
      body: JSON.stringify({
        operation,
        request_id: crypto.randomUUID(),
        reason,
        logical_run_date: sydneyDate(),
      }),
    },
  );
}
