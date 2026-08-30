export const SYSTEM_EVIDENCE_SCHEMA_VERSION = "public-system-evidence-snapshot.v2" as const;
export const SYSTEM_RUNTIME_OBSERVATION_CONTRACT = "system-runtime-observation.v1" as const;

export const SYSTEM_EVIDENCE_SERVICES = [
  {
    key: "storage",
    label: "Amazon S3",
    responsibility: "Iceberg data files and Athena query results; resource names and paths remain private.",
  },
  {
    key: "catalog",
    label: "AWS Glue",
    responsibility: "Governed table metadata for production analytics and isolated staging lifecycle data.",
  },
  {
    key: "analytics",
    label: "Amazon Athena",
    responsibility: "Cutoff-safe SQL analytics and Iceberg operations with bounded failure handling.",
  },
  {
    key: "compute",
    label: "AWS Lambda",
    responsibility: "Deterministic orchestration, validation, export, and bounded release functions.",
  },
  {
    key: "reliability",
    label: "Scheduler + SQS",
    responsibility: "Production scheduling, bounded retries, and encrypted dead-letter recovery.",
  },
  {
    key: "observability",
    label: "CloudWatch + SNS",
    responsibility: "Safe alarms and notifications while subscriber details remain protected.",
  },
] as const;

export type SystemEvidenceService = {
  key: typeof SYSTEM_EVIDENCE_SERVICES[number]["key"];
  label: string;
  status: "DEPLOYED_ARCHITECTURE" | "RUNTIME_VERIFIED";
  responsibility: string;
};

export type SystemEvidenceSnapshot = {
  schema_version: typeof SYSTEM_EVIDENCE_SCHEMA_VERSION;
  as_of_date: string;
  evidence_class: "REPOSITORY_ARCHITECTURE" | "AWS_RUNTIME_INSPECTION";
  live_aws_inspection: boolean;
  read_only: true;
  disclosure: string;
  source_provenance: {
    mode: "REPOSITORY_DOCUMENTS" | "AWS_CONTROL_PLANE_READS";
    observation_contract: null | typeof SYSTEM_RUNTIME_OBSERVATION_CONTRACT;
    athena_query_started: false;
    external_write: false;
    identifiers_retained: false;
  };
  production_track: {
    status: "DOCUMENTED_DEPLOYED" | "RUNTIME_VERIFIED";
    scheduler_target: "PROD_ALIAS";
    immutable_alias: true;
  };
  staging_track: {
    status: "DEPLOYED_VERIFIED" | "RUNTIME_VERIFIED";
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

const exactKeys = (value: Record<string, unknown>, keys: string[]) => (
  Object.keys(value).sort().join("|") === [...keys].sort().join("|")
);

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);

export function validateSystemEvidenceSnapshot(value: unknown, currentSydneyDate: string): SystemEvidenceSnapshot {
  if (!isRecord(value) || !exactKeys(value, [
    "schema_version", "as_of_date", "evidence_class", "live_aws_inspection",
    "read_only", "disclosure", "source_provenance", "production_track", "staging_track",
    "reliability", "services", "authority",
  ])) throw new Error("SYSTEM_EVIDENCE_ENVELOPE_INVALID");

  if (
    value.schema_version !== SYSTEM_EVIDENCE_SCHEMA_VERSION
    || value.read_only !== true
    || typeof value.as_of_date !== "string"
    || !/^\d{4}-\d{2}-\d{2}$/.test(value.as_of_date)
    || value.as_of_date > currentSydneyDate
    || typeof value.disclosure !== "string"
    || !value.disclosure.includes("not production readiness")
  ) throw new Error("SYSTEM_EVIDENCE_BOUNDARY_INVALID");

  const runtimeMode = value.evidence_class === "AWS_RUNTIME_INSPECTION";
  const repositoryMode = value.evidence_class === "REPOSITORY_ARCHITECTURE";
  if ((!runtimeMode && !repositoryMode) || value.live_aws_inspection !== runtimeMode) {
    throw new Error("SYSTEM_EVIDENCE_MODE_INVALID");
  }

  const provenance = value.source_provenance;
  const expectedProvenance = runtimeMode ? {
    mode: "AWS_CONTROL_PLANE_READS",
    observation_contract: SYSTEM_RUNTIME_OBSERVATION_CONTRACT,
    athena_query_started: false,
    external_write: false,
    identifiers_retained: false,
  } : {
    mode: "REPOSITORY_DOCUMENTS",
    observation_contract: null,
    athena_query_started: false,
    external_write: false,
    identifiers_retained: false,
  };
  if (!isRecord(provenance) || !exactKeys(provenance, Object.keys(expectedProvenance))
    || Object.entries(expectedProvenance).some(([key, expected]) => provenance[key] !== expected)
  ) throw new Error("SYSTEM_EVIDENCE_PROVENANCE_INVALID");

  if (repositoryMode && !value.disclosure.includes("not live AWS status")) {
    throw new Error("SYSTEM_EVIDENCE_BOUNDARY_INVALID");
  }
  if (runtimeMode && !value.disclosure.includes("aggregate read-only AWS control-plane inspection")) {
    throw new Error("SYSTEM_EVIDENCE_BOUNDARY_INVALID");
  }

  const production = value.production_track;
  if (!isRecord(production) || !exactKeys(production, ["status", "scheduler_target", "immutable_alias"])
    || production.status !== (runtimeMode ? "RUNTIME_VERIFIED" : "DOCUMENTED_DEPLOYED")
    || production.scheduler_target !== "PROD_ALIAS"
    || production.immutable_alias !== true
  ) throw new Error("SYSTEM_EVIDENCE_PRODUCTION_TRACK_INVALID");

  const staging = value.staging_track;
  if (!isRecord(staging) || !exactKeys(staging, [
    "status", "manual_only", "scheduler_present", "production_alias_present", "production_table_write",
  ]) || staging.status !== (runtimeMode ? "RUNTIME_VERIFIED" : "DEPLOYED_VERIFIED")
    || staging.manual_only !== true || staging.scheduler_present !== false
    || staging.production_alias_present !== false || staging.production_table_write !== false
  ) throw new Error("SYSTEM_EVIDENCE_STAGING_TRACK_INVALID");

  const reliability = value.reliability;
  if (!isRecord(reliability) || !exactKeys(reliability, [
    "stage_count", "quality_check_count", "retry_count", "max_event_age_hours", "dlq_retention_days",
  ]) || reliability.stage_count !== 6 || reliability.quality_check_count !== 10
    || reliability.retry_count !== 2 || reliability.max_event_age_hours !== 24
    || reliability.dlq_retention_days !== 14
  ) throw new Error("SYSTEM_EVIDENCE_RELIABILITY_INVALID");

  if (!Array.isArray(value.services) || value.services.length !== SYSTEM_EVIDENCE_SERVICES.length) {
    throw new Error("SYSTEM_EVIDENCE_SERVICES_INVALID");
  }
  value.services.forEach((service, index) => {
    const expected = SYSTEM_EVIDENCE_SERVICES[index];
    if (!isRecord(service) || !exactKeys(service, ["key", "label", "status", "responsibility"])
      || service.key !== expected.key || service.label !== expected.label
      || service.status !== (runtimeMode ? "RUNTIME_VERIFIED" : "DEPLOYED_ARCHITECTURE")
      || service.responsibility !== expected.responsibility
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
