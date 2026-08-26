import { validateOutcomeComparisonResponse } from "./outcome-comparison-envelope";

export type ActionStatus = "PROPOSED" | "EDITED" | "APPROVED" | "REJECTED" | "COMPLETED";
export type ActionOperation = "EDIT" | "APPROVE" | "REJECT" | "COMPLETE";

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
  decision_brief_version: "decision-brief.v1" | null;
  selected_alternative: string | null;
  selection_rationale: string | null;
  action_owner: string | null;
  action_due_date: string | null;
  created_date: string;
};

export type RiskStatus = "OPEN" | "RESOLVED";

type DecisionBriefBaseV1 = {
  schema_version: "decision-brief.v1";
  as_of_date: string;
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_ALERT";
  };
  urgency: {
    status: "IMMEDIATE_REVIEW" | "REVIEW_WITHIN_4_HOURS" | "REVIEW_SAME_DAY" | "MONITOR";
    basis: string;
    evidence_class: "DERIVED_EXPOSURE";
  };
  benefit_estimate: {
    status: "NOT_ESTIMATED";
    estimate_evidence_class: "NOT_ESTIMATED";
    assumption_set_version: null;
  };
  governance: {
    human_review_required: true;
    execution_authorized: false;
    outcome_observed: false;
    financial_value_estimated: false;
    deterministic_rule: true;
  };
};

export type SlaDecisionBriefV1 = DecisionBriefBaseV1 & {
  decision_type: "SLA_BREACH";
  risk: {
    severity: string;
    milestone: string;
    evidence_class: "OBSERVED_INPUT";
  };
  exposure: {
    metric_name: string;
    delay_hours: number;
    threshold_hours: number;
    breach_margin_hours: number;
    affected_shipments: 1;
    monetary_value: null;
    evidence_class: "DERIVED_EXPOSURE";
  };
  recommendation: {
    action_type: "EXPEDITE_MILESTONE";
    rationale: string;
    evidence_class: "DERIVED_EXPOSURE";
  };
  alternatives: {
    action_type: "EXPEDITE_MILESTONE" | "MONITOR_NEXT_MILESTONE" | "NO_ACTION";
    label: string;
    recommended: boolean;
  }[];
  no_action_exposure: {
    status: "DERIVED";
    delay_hours_at_risk: number;
    breach_margin_hours: number;
    monetary_value: null;
    evidence_class: "DERIVED_EXPOSURE";
  };
};

export type CostDecisionBriefV1 = Omit<DecisionBriefBaseV1, "source"> & {
  decision_type: "COST_ANOMALY";
  source: DecisionBriefBaseV1["source"] & {
    source_contract_version: "stateful-cost-variance.v1";
    rate_card_version: null;
    rate_card_version_status: "UNAVAILABLE_IN_ALERT_CONTRACT";
  };
  risk: {
    severity: string;
    cost_scope: "TOTAL_COST";
    evidence_class: "OBSERVED_INPUT";
  };
  exposure: {
    metric_name: "cost_variance_pct";
    variance_pct: number;
    threshold_pct: number;
    breach_margin_pct: number;
    affected_shipments: 1;
    monetary_value: null;
    evidence_class: "DERIVED_EXPOSURE";
  };
  recommendation: {
    action_type: "REVIEW_COST";
    rationale: string;
    evidence_class: "DERIVED_EXPOSURE";
  };
  alternatives: {
    action_type: "REVIEW_COST" | "MONITOR_COST" | "NO_ACTION";
    label: string;
    recommended: boolean;
  }[];
  no_action_exposure: {
    status: "DERIVED";
    variance_pct_at_risk: number;
    breach_margin_pct: number;
    monetary_value: null;
    evidence_class: "DERIVED_EXPOSURE";
  };
};

export type DecisionBriefV1 = SlaDecisionBriefV1 | CostDecisionBriefV1;

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
  decision_brief: DecisionBriefV1 | null;
};

export type OutcomeStatus = "PENDING" | "SUCCESSFUL" | "PARTIALLY_SUCCESSFUL" | "FAILED" | "INCONCLUSIVE";

export type OperationsOutcome = {
  outcome_id: string;
  action_id: string;
  alert_fingerprint: string;
  shipment_id: string;
  observation_due_date: string;
  outcome_status: OutcomeStatus;
  observed_date: string | null;
  effect_pct: string | null;
  outcome_version: string;
  as_of_date: string;
  evidence_status: "NOT_OBSERVED" | "OBSERVED_ACTUAL_CALENDAR";
  action_type: string | null;
  alert_type: string | null;
  alert_severity: string | null;
  action_status: ActionStatus | null;
  decision_brief_version: "decision-brief.v1" | null;
  selected_alternative: string | null;
};

export type OutcomeCohortSummary = {
  schema_version: "outcome-cohort-summary.v1";
  as_of_date: string;
  status: "AVAILABLE" | "NO_ELIGIBLE_BOUND_OUTCOMES";
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT";
  };
  eligibility: {
    observed_only: true;
    pending_excluded: true;
    unbound_actions_excluded: true;
    future_simulations_excluded: true;
  };
  cohorts: Array<{
    decision_brief_version: string;
    selected_alternative: string;
    observed_outcome_count: number;
    status_counts: {
      successful: number;
      partially_successful: number;
      failed: number;
      inconclusive: number;
    };
    effect_pct: { minimum: number; average: number; maximum: number };
    evidence_sufficiency: {
      status: "PENDING_HUMAN_APPROVAL" | "INSUFFICIENT_EVIDENCE" | "SUFFICIENT_FOR_DESCRIPTIVE_COMPARISON";
      distinct_result_states: number;
      sample_gate_met: boolean | null;
      result_coverage_gate_met: boolean | null;
      comparison_eligible: boolean;
    };
    evidence_gap: {
      schema_version: "outcome-cohort-evidence-gap.v1";
      status: "PENDING_HUMAN_APPROVAL" | "GAP_REMAINS" | "TARGET_MET";
      target_contract_version: string | null;
      additional_observed_outcomes: number | null;
      additional_distinct_result_states: number | null;
      calculation_only: true;
      outcome_collection_recommended: false;
      outcome_creation_authorized: false;
      lifecycle_continuation_authorized: false;
    };
  }>;
  evidence_sufficiency_gate: {
    schema_version: "outcome-cohort-evidence-sufficiency.v1";
    configuration_status: "PENDING_HUMAN_APPROVAL" | "HUMAN_APPROVED_CONTRACT";
    threshold_contract_version: string | null;
    thresholds: {
      minimum_observed_outcomes: number | null;
      minimum_distinct_result_states: number | null;
    };
    comparison_scope: "DESCRIPTIVE_SYNTHETIC_ONLY";
    any_comparison_eligible: boolean;
  };
  descriptive_comparison_view?: {
    schema_version: "outcome-cohort-descriptive-comparison.v1";
    status: "AVAILABLE" | "INSUFFICIENT_ELIGIBLE_COHORTS";
    required_eligible_cohort_count: 2;
    eligible_cohort_count: number;
    excluded_cohort_count: number;
    cohorts: Array<{
      decision_brief_version: string;
      selected_alternative: string;
      observed_outcome_count: number;
      status_percentages: {
        successful: number;
        partially_successful: number;
        failed: number;
        inconclusive: number;
      };
      effect_pct: { minimum: number; average: number; maximum: number };
      provenance: {
        schema_version: "outcome-cohort-comparison-provenance.v1";
        decision_binding: {
          binding_source: "IMMUTABLE_ACTION_PROPOSAL";
          decision_brief_version: string;
          selected_alternative: string;
        };
        evidence_contract: {
          cohort_summary_schema_version: "outcome-cohort-summary.v1";
          threshold_contract_version: string;
          as_of_date: string;
          execution_mode: "OPERATIONAL";
          time_basis: "ACTUAL_CALENDAR";
          evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT";
          observed_only: true;
          pending_excluded: true;
          unbound_actions_excluded: true;
          future_simulations_excluded: true;
        };
        privacy: {
          action_identifiers_exposed: false;
          outcome_identifiers_exposed: false;
          shipment_identifiers_exposed: false;
        };
        read_only: true;
      };
      integrity?: {
        schema_version: "outcome-cohort-comparison-fingerprint.v1";
        algorithm: "SHA-256";
        canonicalization: "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS";
        digest: string;
        covered_fields: [
          "decision_brief_version",
          "selected_alternative",
          "observed_outcome_count",
          "status_percentages",
          "effect_pct",
          "provenance",
        ];
        verification_scope: "RESPONSE_CONTENT_INTEGRITY_ONLY";
        digital_signature: false;
        source_authenticity_attested: false;
        business_validity_attested: false;
      };
    }>;
    comparison_scope: "DESCRIPTIVE_SYNTHETIC_ONLY";
    governance: {
      ranking_produced: false;
      preferred_alternative_selected: false;
      causal_superiority_estimated: false;
      statistical_significance_estimated: false;
      action_recommended: false;
    };
  };
  governance: {
    descriptive_summary_only: true;
    causal_effect_estimate: false;
    financial_value_estimated: false;
    real_logistics_performance: false;
    model_readiness: false;
    policy_activation_authorized: false;
    human_threshold_approval_required: true;
    automatic_threshold_selection: false;
  };
};

export type OutcomeComparisonCohort = NonNullable<
  OutcomeCohortSummary["descriptive_comparison_view"]
>["cohorts"][number];

export type ActionAuditEvent = {
  event_id: string;
  event_type: ActionOperation;
  previous_status: ActionStatus;
  new_status: ActionStatus;
  actor: string;
  reason: string;
  occurred_at: string;
  action_owner: string | null;
  action_due_date: string | null;
};

export type ActionEvidence = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_EVIDENCE";
  };
  chain_status: "ACTION_OPEN" | "ACTION_REJECTED" | "ACTION_COMPLETED_AWAITING_OUTCOME" | "OUTCOME_PENDING" | "OUTCOME_OBSERVED";
  action: OperationsAction;
  events: ActionAuditEvent[];
  outcome: Pick<OperationsOutcome,
    "outcome_id" | "action_id" | "observation_due_date" | "outcome_status" |
    "observed_date" | "effect_pct" | "outcome_version" | "as_of_date" | "evidence_status"
  > | null;
  governance: {
    proposal_immutable: true;
    decision_binding_immutable: true;
    audit_append_only: true;
    outcome_is_simulated: true;
    real_logistics_performance: false;
  };
};

export type LearningEvidence = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  status: "INSUFFICIENT_ELIGIBLE_OUTCOMES" | "ELIGIBLE_AWAITING_PROPOSAL" | "POLICY_PROPOSAL_RECORDED";
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_LEARNING_EVIDENCE";
  };
  gate: {
    minimum_observed_outcomes: number;
    eligible_observed_outcomes: number;
    remaining_outcomes: number;
    gate_met: boolean;
  };
  outcome_summary: {
    successful: number;
    partially_successful: number;
    failed: number;
    inconclusive: number;
    success_rate_pct: number | null;
  };
  proposal: {
    proposal_id: string;
    source_policy_version: string;
    status: string;
    observed_outcome_count: number;
    success_rate_pct: number | null;
    proposed_change: string;
    simulation_config_change: boolean;
    effective_date: string | null;
    approved_by: string | null;
    approved_policy_version: string | null;
    rollback_policy_version: string;
    provenance: string;
    created_date: string;
  } | null;
  governance: {
    eligibility_scope: "SYNTHETIC_POLICY_REVIEW_ONLY";
    review_required: true;
    automatic_activation: false;
    deterministic_rules_replaced: false;
    outcomes_are_simulated: true;
    real_logistics_performance: false;
    model_readiness: false;
    production_readiness: false;
  };
};

export type LabelBinaryTargetReadiness = {
  evaluation_eligible: boolean;
  positive_count: number;
  negative_count: number;
  remaining_observed: number;
  remaining_positive: number;
  remaining_negative: number;
  blockers: string[];
};

export type LabelCostTargetReadiness = {
  evaluation_eligible: boolean;
  label_count: number;
  distinct_value_count: number;
  remaining_observed: number;
  remaining_distinct_values: number;
  blockers: string[];
};

export type ProviderLabelReadiness = {
  schema_version: "operations-api.v1";
  label_contract_version: "multimodal_outcome_label_v1";
  readiness_policy_version: "supervised_label_readiness_v1";
  as_of_date: string;
  status: "blocked_insufficient_observed_labels" | "partially_ready" | "ready";
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_LABEL_EVIDENCE";
  };
  thresholds: {
    minimum_observed_per_provider: number;
    minimum_positive_and_negative_per_binary_target: number;
    minimum_distinct_cost_variance_values: number;
  };
  coverage: {
    provider_groups: number;
    ready_provider_groups: number;
    eligible_targets: number;
    total_targets: number;
    observed_labels: number;
    pending_labels: number;
  };
  groups: {
    transport_mode: "AIR" | "OCEAN";
    provider_code: string;
    source_latest_date: string;
    status: "blocked_insufficient_observed_labels" | "partially_ready" | "ready";
    cohort_shipments: number;
    observed_label_count: number;
    pending_label_count: number;
    observed_rate_pct: number | null;
    targets: {
      sla_breach: LabelBinaryTargetReadiness;
      delay_risk: LabelBinaryTargetReadiness;
      cost_variance: LabelCostTargetReadiness;
    };
  }[];
  governance: {
    decision_use: "SUPERVISED_EVALUATION_GATE_ONLY";
    pending_labels_excluded: true;
    future_simulations_included: false;
    entity_identifiers_included: false;
    model_training_authorized: false;
    model_promotion_authorized: false;
    production_readiness: false;
  };
};

export type PipelineCheck = {
  name: string;
  status: "passed" | "failed";
};

export type PipelineStage = {
  name: string;
  status: "blocked" | "running" | "succeeded" | "failed" | "not_invoked";
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  failure_category: string | null;
  quality_checks: PipelineCheck[];
};

export type PipelineHealth = {
  schema_version: "operations-api.v1";
  status: "current" | "stale" | "failed" | "running" | "unverified";
  freshness_status: "current" | "stale" | "future_invalid" | "unverified";
  as_of_date: string;
  logical_run_date: string | null;
  started_at: string | null;
  completed_at: string | null;
  failed_stage: string | null;
  failure_category: string | null;
  stages: PipelineStage[];
  stage_count: number;
  stages_succeeded: number;
  quality_checks_succeeded: number;
  quality_checks_total: number;
  runbook_url: string;
};

export type ForecastPoint = {
  date: string;
  predicted_shipments: number;
  lower_bound: number;
  upper_bound: number;
  evidence_status: "ADVISORY_FORECAST_NOT_OBSERVED";
};

export type ForecastContract = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  source: {
    execution_mode: "OPERATIONAL";
    time_basis: "ACTUAL_CALENDAR";
    evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE";
    feature_contract_version: string;
  };
  forecast: {
    status: "ready" | "insufficient_operational_history";
    execution_mode: "FUTURE_SIMULATION";
    time_basis: "MODEL_PROJECTION";
    scenario_id: string;
    method: string;
    model_version: string;
    horizon_days: number;
    training_start: string | null;
    training_end: string | null;
    points: ForecastPoint[];
    decision_use: "ADVISORY_ONLY";
    production_effect: false;
  };
  accuracy: {
    status: "engineering_evidence" | "insufficient_operational_history";
    evaluation_policy: string;
    evidence_class: "SYNTHETIC_ENGINEERING_BACKTEST";
    metrics: {
      forecast_count: number;
      mae: number;
      rmse: number;
      bias: number;
      mape_pct: number | null;
      interval_coverage_pct: number;
    } | null;
    model_promotion_status: "BLOCKED";
  };
  coverage: {
    window_days: number;
    eligible_dates: number;
    latest_eligible_date: string | null;
    minimum_training_dates: number;
    minimum_accuracy_forecasts: number;
  };
  history: { date: string; shipments: number; evidence_status: string }[];
  disclosure: string;
};

export type NetworkSummary = {
  transport_mode: "AIR" | "OCEAN";
  provider_code: string;
  market_lane: string;
  shipment_count: string;
  active_shipment_count: string;
  sla_breach_count: string;
  sla_breach_rate_pct: string;
  avg_planned_p2p_hours: string | null;
  avg_actual_p2p_hours: string | null;
};

export type ShipmentEntity = {
  metric_date: string;
  shipment_id: string;
  transport_mode: "AIR" | "OCEAN";
  provider_code: string;
  market_lane: string;
  service_level: string;
  lifecycle_stage: string;
  lifecycle_status: "OPEN" | "CLOSED";
  sla_breach_flag: "true" | "false";
  planned_p2p_hours: string | null;
  actual_p2p_hours: string | null;
};

type OperationalSource = {
  execution_mode: "OPERATIONAL";
  time_basis: "ACTUAL_CALENDAR";
  evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_BASELINE";
};

export type NetworkResponse = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  source: OperationalSource;
  entity_access: boolean;
  items: NetworkSummary[];
  next_token: null;
};

export type ShipmentResponse = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  source: OperationalSource;
  items: ShipmentEntity[];
  next_token: string | null;
};

type QueueResponse = {
  schema_version: "operations-api.v1";
  items: OperationsAction[];
  next_token: string | null;
};

type RiskResponse = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  items: OperationsRisk[];
  next_token: string | null;
};

type OutcomeResponse = {
  schema_version: "operations-api.v1";
  as_of_date: string;
  items: OperationsOutcome[];
  cohort_summary?: OutcomeCohortSummary;
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

export async function loadActionEvidence(token: string, actionId: string) {
  return request<ActionEvidence>(
    `/v1/actions/${encodeURIComponent(actionId)}/evidence`, token,
  );
}

export async function loadRiskHotspots(token: string, status?: RiskStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}&limit=100` : "?limit=100";
  return request<RiskResponse>(`/v1/risks${query}`, token);
}

export async function loadOutcomeReview(token: string, status?: OutcomeStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}&limit=100` : "?limit=100";
  const response = await request<unknown>(`/v1/outcomes${query}`, token);
  validateOutcomeComparisonResponse(response);
  return response as OutcomeResponse;
}

export async function loadLearningEvidence(token: string) {
  return request<LearningEvidence>("/v1/learning", token);
}

export async function loadLabelReadiness(token: string) {
  return request<ProviderLabelReadiness>("/v1/label-readiness", token);
}

export async function loadPipelineHealth(token: string) {
  return request<PipelineHealth>("/v1/pipeline-health", token);
}

export async function loadForecastAccuracy(token: string) {
  return request<ForecastContract>("/v1/forecasts", token);
}

export async function loadNetworkSummary(
  token: string, filters: { mode?: string; provider?: string; lane?: string } = {},
) {
  const query = new URLSearchParams();
  if (filters.mode) query.set("mode", filters.mode);
  if (filters.provider) query.set("provider", filters.provider);
  if (filters.lane) query.set("lane", filters.lane);
  const suffix = query.size ? `?${query.toString()}` : "";
  return request<NetworkResponse>(`/v1/network${suffix}`, token);
}

export async function loadShipmentDrilldown(
  token: string,
  filters: { mode?: string; provider?: string; lane?: string; status?: string; nextToken?: string },
) {
  const query = new URLSearchParams({ limit: "25" });
  if (filters.mode) query.set("mode", filters.mode);
  if (filters.provider) query.set("provider", filters.provider);
  if (filters.lane) query.set("lane", filters.lane);
  if (filters.status) query.set("status", filters.status);
  if (filters.nextToken) query.set("next_token", filters.nextToken);
  return request<ShipmentResponse>(`/v1/shipments?${query.toString()}`, token);
}

export async function mutateAction(
  token: string, actionId: string, operation: ActionOperation, reason: string,
  assignment: { actionOwner?: string; actionDueDate?: string } = {},
) {
  return request<{ schema_version: string; action: { action_status: ActionStatus } }>(
    `/v1/actions/${encodeURIComponent(actionId)}/events`, token, {
      method: "POST",
      body: JSON.stringify({
        operation,
        request_id: crypto.randomUUID(),
        reason,
        action_owner: assignment.actionOwner,
        action_due_date: assignment.actionDueDate,
      }),
    },
  );
}
