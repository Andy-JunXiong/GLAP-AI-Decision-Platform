const ENVELOPE_ERROR = "Outcome comparison envelope failed closed";

function fail(): never {
  throw new Error(ENVELOPE_ERROR);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function hasCohortIdentity(value: unknown): value is Record<string, unknown> {
  return isRecord(value)
    && typeof value.decision_brief_version === "string"
    && value.decision_brief_version.length > 0
    && typeof value.selected_alternative === "string"
    && value.selected_alternative.length > 0
    && isNonNegativeInteger(value.observed_outcome_count);
}

export function validateOutcomeComparisonResponse(response: unknown): void {
  if (!isRecord(response)) fail();

  const summary = response.cohort_summary;
  if (summary === undefined) return;
  if (!isRecord(summary) || !Array.isArray(summary.cohorts)) fail();

  const envelope = summary.descriptive_comparison_view;
  if (envelope === undefined) return;
  if (!isRecord(envelope)) fail();

  const status = envelope.status;
  const eligibleCount = envelope.eligible_cohort_count;
  const excludedCount = envelope.excluded_cohort_count;
  const cohorts = envelope.cohorts;
  const governance = envelope.governance;

  if (
    envelope.schema_version !== "outcome-cohort-descriptive-comparison.v1"
    || (status !== "AVAILABLE" && status !== "INSUFFICIENT_ELIGIBLE_COHORTS")
    || envelope.required_eligible_cohort_count !== 2
    || envelope.comparison_scope !== "DESCRIPTIVE_SYNTHETIC_ONLY"
    || !isNonNegativeInteger(eligibleCount)
    || !isNonNegativeInteger(excludedCount)
    || eligibleCount + excludedCount !== summary.cohorts.length
    || !Array.isArray(cohorts)
    || !cohorts.every(hasCohortIdentity)
    || !isRecord(governance)
    || governance.ranking_produced !== false
    || governance.preferred_alternative_selected !== false
    || governance.causal_superiority_estimated !== false
    || governance.statistical_significance_estimated !== false
    || governance.action_recommended !== false
  ) fail();

  if (status === "AVAILABLE") {
    if (eligibleCount < 2 || cohorts.length !== eligibleCount) fail();
    return;
  }

  if (eligibleCount >= 2 || cohorts.length !== 0) fail();
}
