export const SYSTEM_EVIDENCE_SCHEMA_VERSION = "public-system-evidence-snapshot.v1" as const;

export type SystemEvidenceService = {
  key: "storage" | "catalog" | "analytics" | "compute" | "reliability" | "observability";
  label: string;
  status: "DEPLOYED_ARCHITECTURE";
  responsibility: string;
};

export type SystemEvidenceSnapshot = {
  schema_version: typeof SYSTEM_EVIDENCE_SCHEMA_VERSION;
  repository_as_of_date: string;
  evidence_class: "REPOSITORY_ARCHITECTURE";
  live_aws_inspection: false;
  read_only: true;
  disclosure: string;
  production_track: {
    status: "DOCUMENTED_DEPLOYED";
    scheduler_target: "PROD_ALIAS";
    immutable_alias: true;
  };
  staging_track: {
    status: "DEPLOYED_VERIFIED";
    manual_only: true;
    scheduler_present: false;
    production_alias_present: false;
    production_table_write: false;
  };
  reliability: {
    stage_count: 6;
    quality_check_count: 10;
    retry_count: 2;
    max_event_age_hours: 24;
    dlq_retention_days: 14;
  };
  services: SystemEvidenceService[];
  authority: {
    aws_write: false;
    infrastructure_change: false;
    production_alias_move: false;
    schedule_change: false;
    action_mutation: false;
    policy_activation: false;
    model_promotion: false;
  };
};

const expectedServiceKeys: SystemEvidenceService["key"][] = [
  "storage",
  "catalog",
  "analytics",
  "compute",
  "reliability",
  "observability",
];

const exactKeys = (value: Record<string, unknown>, keys: string[]) => (
  Object.keys(value).sort().join("|") === [...keys].sort().join("|")
);

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);

export function validateSystemEvidenceSnapshot(value: unknown, currentSydneyDate: string): SystemEvidenceSnapshot {
  if (!isRecord(value) || !exactKeys(value, [
    "schema_version", "repository_as_of_date", "evidence_class", "live_aws_inspection",
    "read_only", "disclosure", "production_track", "staging_track", "reliability",
    "services", "authority",
  ])) throw new Error("SYSTEM_EVIDENCE_ENVELOPE_INVALID");

  if (
    value.schema_version !== SYSTEM_EVIDENCE_SCHEMA_VERSION
    || value.evidence_class !== "REPOSITORY_ARCHITECTURE"
    || value.live_aws_inspection !== false
    || value.read_only !== true
    || typeof value.repository_as_of_date !== "string"
    || !/^\d{4}-\d{2}-\d{2}$/.test(value.repository_as_of_date)
    || value.repository_as_of_date > currentSydneyDate
    || typeof value.disclosure !== "string"
    || !value.disclosure.includes("not live AWS status")
  ) throw new Error("SYSTEM_EVIDENCE_BOUNDARY_INVALID");

  const production = value.production_track;
  if (!isRecord(production) || !exactKeys(production, ["status", "scheduler_target", "immutable_alias"])
    || production.status !== "DOCUMENTED_DEPLOYED"
    || production.scheduler_target !== "PROD_ALIAS"
    || production.immutable_alias !== true
  ) throw new Error("SYSTEM_EVIDENCE_PRODUCTION_TRACK_INVALID");

  const staging = value.staging_track;
  if (!isRecord(staging) || !exactKeys(staging, [
    "status", "manual_only", "scheduler_present", "production_alias_present", "production_table_write",
  ]) || staging.status !== "DEPLOYED_VERIFIED" || staging.manual_only !== true
    || staging.scheduler_present !== false || staging.production_alias_present !== false
    || staging.production_table_write !== false
  ) throw new Error("SYSTEM_EVIDENCE_STAGING_TRACK_INVALID");

  const reliability = value.reliability;
  if (!isRecord(reliability) || !exactKeys(reliability, [
    "stage_count", "quality_check_count", "retry_count", "max_event_age_hours", "dlq_retention_days",
  ]) || reliability.stage_count !== 6 || reliability.quality_check_count !== 10
    || reliability.retry_count !== 2 || reliability.max_event_age_hours !== 24
    || reliability.dlq_retention_days !== 14
  ) throw new Error("SYSTEM_EVIDENCE_RELIABILITY_INVALID");

  if (!Array.isArray(value.services) || value.services.length !== expectedServiceKeys.length) {
    throw new Error("SYSTEM_EVIDENCE_SERVICES_INVALID");
  }
  value.services.forEach((service, index) => {
    if (!isRecord(service) || !exactKeys(service, ["key", "label", "status", "responsibility"])
      || service.key !== expectedServiceKeys[index] || typeof service.label !== "string"
      || service.status !== "DEPLOYED_ARCHITECTURE" || typeof service.responsibility !== "string"
      || service.label.length < 2 || service.responsibility.length < 10
    ) throw new Error("SYSTEM_EVIDENCE_SERVICE_INVALID");
  });

  const authority = value.authority;
  const authorityKeys = [
    "aws_write", "infrastructure_change", "production_alias_move", "schedule_change",
    "action_mutation", "policy_activation", "model_promotion",
  ];
  if (!isRecord(authority) || !exactKeys(authority, authorityKeys)
    || authorityKeys.some((key) => authority[key] !== false)
  ) throw new Error("SYSTEM_EVIDENCE_AUTHORITY_INVALID");

  return value as SystemEvidenceSnapshot;
}

export function currentSydneyDate() {
  const parts = new Intl.DateTimeFormat("en-AU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Australia/Sydney",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

export async function loadSystemEvidenceSnapshot(): Promise<SystemEvidenceSnapshot> {
  const response = await fetch("/data/system-evidence-snapshot.json", { cache: "no-store" });
  if (!response.ok) throw new Error("SYSTEM_EVIDENCE_FETCH_FAILED");
  return validateSystemEvidenceSnapshot(await response.json(), currentSydneyDate());
}
