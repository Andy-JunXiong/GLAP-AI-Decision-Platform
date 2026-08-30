import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the GLAP customer control tower", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>GLAP Logistics Decision Platform<\/title>/i);
  assert.match(html, /Control Tower/);
  assert.match(html, /Network risk picture/);
  assert.match(html, /Needs your attention/);
  assert.match(html, /Divert 8 FCL via Melbourne/);
  assert.match(html, /Illustrative scenario value/);
  assert.match(html, /data-claim-id="next-portfolio-value"/);
  assert.match(html, /Fixed illustrative portfolio · not execution evidence/);
  assert.match(html, /Action Board/);
  assert.match(html, /property="og:image" content="\/og\.png"/);
});

test("includes the generated social card", async () => {
  await access(new URL("../public/og.png", import.meta.url));
});

test("filters the authenticated Decision Queue by severity without changing Action state", async () => {
  const {
    decisionSeverityCount,
    decisionSeverityFilters,
    filterDecisionQueue,
    waitingDecisionActions,
  } = await import("../app/decision-queue-filter.ts");
  const action = (actionId, severity, status) => ({
    action_id: actionId,
    alert_fingerprint: `alert-${actionId}`,
    shipment_id: `shipment-${actionId}`,
    action_type: "EXPEDITE_MILESTONE",
    alert_type: "SLA_BREACH",
    alert_severity: severity,
    status,
    approval_required: "YES",
    approved_by: null,
    approved_at: null,
    completed_at: null,
    decision_brief_version: "decision-brief.v1",
    selected_alternative: "EXPEDITE_MILESTONE",
    selection_rationale: "Bound rationale",
    action_owner: null,
    action_due_date: null,
    created_date: "2026-08-27",
  });
  const actions = [
    action("medium-proposed", "MEDIUM", "PROPOSED"),
    action("medium-edited", "medium", "EDITED"),
    action("high-proposed", "HIGH", "PROPOSED"),
    action("medium-completed", "MEDIUM", "COMPLETED"),
  ];

  assert.deepEqual(decisionSeverityFilters, ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"]);
  assert.deepEqual(waitingDecisionActions(actions).map((item) => item.action_id), [
    "medium-proposed",
    "medium-edited",
    "high-proposed",
  ]);
  assert.deepEqual(filterDecisionQueue(actions, "MEDIUM").map((item) => item.action_id), [
    "medium-proposed",
    "medium-edited",
  ]);
  assert.equal(decisionSeverityCount(actions, "MEDIUM"), 2);
  assert.equal(decisionSeverityCount(actions, "LOW"), 0);
  assert.equal(actions[3].status, "COMPLETED");
});

test("opens an Action review only when its immutable Decision Brief binding reconciles", async () => {
  const {
    decisionReviewHandoffMessage,
    resolveDecisionReviewHandoff,
  } = await import("../app/decision-review-handoff.ts");
  const rationale = "Review an expedite intervention for P2P_ARRIVAL.";
  const brief = {
    schema_version: "decision-brief.v1",
    as_of_date: "2026-08-27",
    decision_type: "SLA_BREACH",
    source: {
      execution_mode: "OPERATIONAL",
      time_basis: "ACTUAL_CALENDAR",
      evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_ALERT",
    },
    risk: { severity: "MEDIUM", milestone: "P2P_ARRIVAL", evidence_class: "OBSERVED_INPUT" },
    exposure: {
      metric_name: "governed_delay_hours",
      delay_hours: 84,
      threshold_hours: 48,
      breach_margin_hours: 36,
      affected_shipments: 1,
      monetary_value: null,
      evidence_class: "DERIVED_EXPOSURE",
    },
    recommendation: {
      action_type: "EXPEDITE_MILESTONE",
      rationale,
      evidence_class: "DERIVED_EXPOSURE",
    },
    alternatives: [
      { action_type: "EXPEDITE_MILESTONE", label: "Expedite milestone", recommended: true },
      { action_type: "NO_ACTION", label: "No action", recommended: false },
    ],
    no_action_exposure: {
      status: "DERIVED",
      delay_hours_at_risk: 84,
      breach_margin_hours: 36,
      monetary_value: null,
      evidence_class: "DERIVED_EXPOSURE",
    },
    urgency: { status: "REVIEW_SAME_DAY", basis: "SLA breach", evidence_class: "DERIVED_EXPOSURE" },
    benefit_estimate: { status: "NOT_ESTIMATED", estimate_evidence_class: "NOT_ESTIMATED", assumption_set_version: null },
    governance: {
      human_review_required: true,
      execution_authorized: false,
      outcome_observed: false,
      financial_value_estimated: false,
      deterministic_rule: true,
    },
  };
  const action = {
    action_id: "action-1",
    alert_fingerprint: "alert-1",
    shipment_id: "shipment-1",
    action_type: "EXPEDITE_MILESTONE",
    alert_type: "SLA_BREACH",
    alert_severity: "MEDIUM",
    status: "PROPOSED",
    approval_required: "YES",
    approved_by: null,
    approved_at: null,
    completed_at: null,
    decision_brief_version: "decision-brief.v1",
    selected_alternative: "EXPEDITE_MILESTONE",
    selection_rationale: rationale,
    action_owner: null,
    action_due_date: null,
    created_date: "2026-08-27",
  };
  const risk = {
    alert_fingerprint: "alert-1",
    shipment_id: "shipment-1",
    alert_type: "SLA_BREACH",
    alert_grain: "SHIPMENT_MILESTONE",
    alert_dimension: "P2P_ARRIVAL",
    severity: "MEDIUM",
    status: "OPEN",
    first_detected_date: "2026-08-27",
    last_detected_date: "2026-08-27",
    resolved_date: null,
    metric_name: "governed_delay_hours",
    metric_value: "84",
    threshold_value: "48",
    as_of_date: "2026-08-27",
    decision_brief: brief,
  };

  assert.deepEqual(resolveDecisionReviewHandoff(action, [risk]), { status: "READY", brief });
  assert.deepEqual(resolveDecisionReviewHandoff(action, []), { status: "BLOCKED", reason_code: "MISSING_RISK" });
  assert.deepEqual(resolveDecisionReviewHandoff(action, [risk, structuredClone(risk)]), { status: "BLOCKED", reason_code: "AMBIGUOUS_RISK" });

  const resolvedRisk = { ...risk, status: "RESOLVED" };
  assert.deepEqual(resolveDecisionReviewHandoff(action, [resolvedRisk]), { status: "BLOCKED", reason_code: "RISK_NOT_OPEN" });

  const missingBrief = { ...risk, decision_brief: null };
  assert.deepEqual(resolveDecisionReviewHandoff(action, [missingBrief]), { status: "BLOCKED", reason_code: "MISSING_DECISION_BRIEF" });

  const incompleteAction = { ...action, decision_brief_version: null };
  assert.deepEqual(resolveDecisionReviewHandoff(incompleteAction, [risk]), { status: "BLOCKED", reason_code: "ACTION_BINDING_INCOMPLETE" });

  const changedSource = structuredClone(risk);
  changedSource.shipment_id = "shipment-2";
  assert.deepEqual(resolveDecisionReviewHandoff(action, [changedSource]), { status: "BLOCKED", reason_code: "SOURCE_MISMATCH" });

  const changedDecision = structuredClone(risk);
  changedDecision.decision_brief.recommendation.action_type = "NO_ACTION";
  assert.deepEqual(resolveDecisionReviewHandoff(action, [changedDecision]), { status: "BLOCKED", reason_code: "DECISION_BINDING_MISMATCH" });

  const changedRationale = structuredClone(risk);
  changedRationale.decision_brief.recommendation.rationale = "Changed rationale";
  assert.deepEqual(resolveDecisionReviewHandoff(action, [changedRationale]), { status: "BLOCKED", reason_code: "RATIONALE_MISMATCH" });
  assert.match(decisionReviewHandoffMessage("RATIONALE_MISMATCH"), /Human review remains blocked and no Action was changed/);
});

test("verifies the server comparison fingerprint and fails closed on drift", async () => {
  const {
    isOutcomeComparisonFingerprintRetryable,
    verifyOutcomeComparisonFingerprint,
  } = await import(
    "../app/outcome-comparison-fingerprint.ts"
  );
  const cohort = {
    decision_brief_version: "decision-brief.v1",
    selected_alternative: "ELIGIBLE",
    observed_outcome_count: 20,
    status_percentages: {
      successful: 50,
      partially_successful: 0,
      failed: 50,
      inconclusive: 0,
    },
    effect_pct: { minimum: -5, average: 2, maximum: 9 },
    provenance: {
      schema_version: "outcome-cohort-comparison-provenance.v1",
      decision_binding: {
        binding_source: "IMMUTABLE_ACTION_PROPOSAL",
        decision_brief_version: "decision-brief.v1",
        selected_alternative: "ELIGIBLE",
      },
      evidence_contract: {
        cohort_summary_schema_version: "outcome-cohort-summary.v1",
        threshold_contract_version: "outcome-cohort-threshold-contract.v1",
        as_of_date: "2026-08-25",
        execution_mode: "OPERATIONAL",
        time_basis: "ACTUAL_CALENDAR",
        evidence_class: "SYNTHETIC_OPERATIONAL_CALENDAR_OUTCOME_COHORT",
        observed_only: true,
        pending_excluded: true,
        unbound_actions_excluded: true,
        future_simulations_excluded: true,
      },
      privacy: {
        action_identifiers_exposed: false,
        outcome_identifiers_exposed: false,
        shipment_identifiers_exposed: false,
      },
      read_only: true,
    },
    integrity: {
      schema_version: "outcome-cohort-comparison-fingerprint.v1",
      algorithm: "SHA-256",
      canonicalization: "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS",
      digest: "2158370e322f20fbb2e73e52d2139bcc18d6c2010678467f95461d6e4f064c73",
      covered_fields: [
        "decision_brief_version",
        "selected_alternative",
        "observed_outcome_count",
        "status_percentages",
        "effect_pct",
        "provenance",
      ],
      verification_scope: "RESPONSE_CONTENT_INTEGRITY_ONLY",
      digital_signature: false,
      source_authenticity_attested: false,
      business_validity_attested: false,
    },
  };
  assert.deepEqual(
    await verifyOutcomeComparisonFingerprint(cohort),
    { status: "VERIFIED", reason_code: "MATCH" },
  );

  const changedMetric = structuredClone(cohort);
  changedMetric.effect_pct.average = 2.01;
  assert.deepEqual(
    await verifyOutcomeComparisonFingerprint(changedMetric),
    { status: "MISMATCH", reason_code: "DIGEST_MISMATCH" },
  );

  const expandedTrust = structuredClone(cohort);
  expandedTrust.integrity.digital_signature = true;
  assert.deepEqual(
    await verifyOutcomeComparisonFingerprint(expandedTrust),
    { status: "MISMATCH", reason_code: "CONTRACT_METADATA_MISMATCH" },
  );

  const missingIntegrity = structuredClone(cohort);
  delete missingIntegrity.integrity;
  assert.deepEqual(
    await verifyOutcomeComparisonFingerprint(missingIntegrity),
    { status: "MISMATCH", reason_code: "MISSING_INTEGRITY" },
  );

  const nonCanonical = structuredClone(cohort);
  nonCanonical.effect_pct.average = 2.001;
  assert.deepEqual(
    await verifyOutcomeComparisonFingerprint(nonCanonical),
    { status: "MISMATCH", reason_code: "NON_CANONICAL_CONTENT" },
  );

  assert.equal(isOutcomeComparisonFingerprintRetryable({
    status: "MISMATCH", reason_code: "CRYPTO_UNAVAILABLE",
  }), true);
  assert.equal(isOutcomeComparisonFingerprintRetryable({
    status: "MISMATCH", reason_code: "VERIFICATION_ERROR",
  }), true);
  assert.equal(isOutcomeComparisonFingerprintRetryable({
    status: "MISMATCH", reason_code: "DIGEST_MISMATCH",
  }), false);
  assert.equal(isOutcomeComparisonFingerprintRetryable({
    status: "VERIFIED", reason_code: "MATCH",
  }), false);
});

test("validates the comparison envelope before the cockpit can iterate it", async () => {
  const { validateOutcomeComparisonResponse } = await import(
    "../app/outcome-comparison-envelope.ts"
  );
  const eligibleCohort = (selectedAlternative) => ({
    decision_brief_version: "decision-brief.v1",
    selected_alternative: selectedAlternative,
    observed_outcome_count: 20,
  });
  const response = {
    cohort_summary: {
      cohorts: [{}, {}, {}],
      descriptive_comparison_view: {
        schema_version: "outcome-cohort-descriptive-comparison.v1",
        status: "AVAILABLE",
        required_eligible_cohort_count: 2,
        eligible_cohort_count: 2,
        excluded_cohort_count: 1,
        cohorts: [eligibleCohort("EXPEDITE"), eligibleCohort("MONITOR")],
        comparison_scope: "DESCRIPTIVE_SYNTHETIC_ONLY",
        governance: {
          ranking_produced: false,
          preferred_alternative_selected: false,
          causal_superiority_estimated: false,
          statistical_significance_estimated: false,
          action_recommended: false,
        },
      },
    },
  };
  assert.doesNotThrow(() => validateOutcomeComparisonResponse(response));
  assert.doesNotThrow(() => validateOutcomeComparisonResponse({}));

  const validInsufficient = structuredClone(response);
  validInsufficient.cohort_summary.cohorts = [{}];
  validInsufficient.cohort_summary.descriptive_comparison_view.status = "INSUFFICIENT_ELIGIBLE_COHORTS";
  validInsufficient.cohort_summary.descriptive_comparison_view.eligible_cohort_count = 1;
  validInsufficient.cohort_summary.descriptive_comparison_view.excluded_cohort_count = 0;
  validInsufficient.cohort_summary.descriptive_comparison_view.cohorts = [];
  assert.doesNotThrow(() => validateOutcomeComparisonResponse(validInsufficient));

  const nonIterable = structuredClone(response);
  nonIterable.cohort_summary.descriptive_comparison_view.cohorts = {};
  assert.throws(
    () => validateOutcomeComparisonResponse(nonIterable),
    /Outcome comparison envelope failed closed/,
  );

  const inconsistentCounts = structuredClone(response);
  inconsistentCounts.cohort_summary.descriptive_comparison_view.excluded_cohort_count = 0;
  assert.throws(
    () => validateOutcomeComparisonResponse(inconsistentCounts),
    /Outcome comparison envelope failed closed/,
  );

  const unavailableStatus = structuredClone(response);
  unavailableStatus.cohort_summary.descriptive_comparison_view.status = "INSUFFICIENT_ELIGIBLE_COHORTS";
  assert.throws(
    () => validateOutcomeComparisonResponse(unavailableStatus),
    /Outcome comparison envelope failed closed/,
  );

  const expandedAuthority = structuredClone(response);
  expandedAuthority.cohort_summary.descriptive_comparison_view.governance.action_recommended = true;
  assert.throws(
    () => validateOutcomeComparisonResponse(expandedAuthority),
    /Outcome comparison envelope failed closed/,
  );
});

test("keeps authenticated Action writes behind the internal API client", async () => {
  const client = await readFile(new URL("../app/operations-api.ts", import.meta.url), "utf8");
  assert.match(client, /NEXT_PUBLIC_GLAP_OPERATIONS_API_URL/);
  assert.match(client, /sessionStorage\.getItem/);
  assert.match(client, /authorization: `Bearer \$\{token\}`/);
  assert.match(client, /\/v1\/actions\/\$\{encodeURIComponent\(actionId\)\}\/events/);
  assert.match(client, /\/v1\/actions\/\$\{encodeURIComponent\(actionId\)\}\/evidence/);
  assert.match(client, /export async function loadActionEvidence/);
  assert.match(client, /"EDIT" \| "APPROVE" \| "REJECT" \| "COMPLETE"/);
  assert.match(client, /action_owner: assignment\.actionOwner/);
  assert.match(client, /action_due_date: assignment\.actionDueDate/);
  assert.match(client, /\/v1\/risks\$\{query\}/);
  assert.match(client, /export async function loadRiskHotspots/);
  assert.match(client, /\/v1\/outcomes\$\{query\}/);
  assert.match(client, /export async function loadOutcomeReview/);
  assert.match(client, /request<unknown>\(`\/v1\/outcomes\$\{query\}`/);
  assert.match(client, /validateOutcomeComparisonResponse\(response\)/);
  assert.match(client, /\/v1\/learning/);
  assert.match(client, /export async function loadLearningEvidence/);
  assert.match(client, /\/v1\/label-readiness/);
  assert.match(client, /export async function loadLabelReadiness/);
  assert.match(client, /\/v1\/pipeline-health/);
  assert.match(client, /export async function loadPipelineHealth/);
  assert.match(client, /\/v1\/forecasts/);
  assert.match(client, /export async function loadForecastAccuracy/);
  assert.match(client, /\/v1\/network/);
  assert.match(client, /export async function loadNetworkSummary/);
  assert.match(client, /\/v1\/shipments/);
  assert.match(client, /export async function loadShipmentDrilldown/);
  assert.doesNotMatch(client, /localStorage/);

  const auth = await readFile(new URL("../app/operations-auth.ts", import.meta.url), "utf8");
  assert.match(auth, /code_challenge_method: "S256"/);
  assert.match(auth, /returnedState !== expectedState/);
  assert.match(auth, /window\.sessionStorage/);
  assert.doesNotMatch(auth, /localStorage/);

  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /loadRiskHotspots\(token, "OPEN"\)/);
  assert.match(page, /title="Risk hotspots"/);
  assert.match(page, /item\.id === "signals"[\s\S]*"Risk Hotspots"/);
  assert.match(page, /risk\.decision_brief \? openBrief\(risk\.decision_brief\)/);
  assert.match(page, /function OperationalDecisionBrief/);
  assert.match(page, /Expected benefit" value="NOT ESTIMATED"/);
  assert.match(client, /decision_type: "COST_ANOMALY"/);
  assert.match(client, /source_contract_version: "stateful-cost-variance\.v1"/);
  assert.match(client, /rate_card_version_status: "UNAVAILABLE_IN_ALERT_CONTRACT"/);
  assert.match(client, /action_type: "REVIEW_COST" \| "MONITOR_COST" \| "NO_ACTION"/);
  assert.match(page, /Review the governed response to a cost anomaly/);
  assert.match(page, /Rate-card version unavailable in Alert contract/);
  assert.match(page, /No rate-card identifier is inferred/);
  assert.match(page, /Deterministic \$\{contract\.decision_type\} rule/);
  assert.match(page, /This brief itself performs no mutation/);
  assert.match(page, /reviewAction\(item\)/);
  assert.match(page, /aria-label="Decision severity filter"/);
  assert.match(page, /decisionSeverityFilters\.map/);
  assert.match(page, /filterDecisionQueue\(actions, severityFilter\)/);
  assert.match(page, /No waiting Actions match this severity/);
  assert.match(page, /Only the Action whose bound Brief you just reviewed is shown/);
  assert.match(page, /visibleActions\.map/);
  assert.match(page, /Back to bound Decision Brief/);
  assert.match(page, /Open selected Action/);
  assert.match(page, /Bound to \$\{item\.decision_brief_version\}/);
  assert.match(page, /selected deterministic alternative/);
  assert.match(page, /Named-human review reasons remain append-only audit events/);
  assert.match(client, /decision_brief_version: "decision-brief\.v1" \| null/);
  assert.match(client, /decision_binding_immutable: true/);
  assert.match(page, /onClick=\{\(\) => go\("decisions"\)\}/);
  assert.match(page, /loadOutcomeReview\(token\)/);
  assert.match(page, /title="Outcome review"/);
  assert.match(page, /Not counted as actual evidence/);
  assert.match(page, /OBSERVED_ACTUAL_CALENDAR/);
  assert.match(client, /decision_brief_version: "decision-brief\.v1" \| null/);
  assert.match(client, /selected_alternative: string \| null/);
  assert.match(client, /schema_version: "outcome-cohort-summary\.v1"/);
  assert.match(client, /descriptive_summary_only: true/);
  assert.match(client, /causal_effect_estimate: false/);
  assert.match(client, /schema_version: "outcome-cohort-evidence-sufficiency\.v1"/);
  assert.match(client, /configuration_status: "PENDING_HUMAN_APPROVAL" \| "HUMAN_APPROVED_CONTRACT"/);
  assert.match(client, /automatic_threshold_selection: false/);
  assert.match(page, /Decision source: \$\{item\.decision_brief_version\}/);
  assert.match(page, /legacy or unbound Action/);
  assert.match(page, /Simulated Outcome effects are not causal estimates or real logistics performance/);
  assert.match(page, /Decision-contract Outcome cohorts/);
  assert.match(page, /No eligible Decision cohorts/);
  assert.match(page, /These cohorts are descriptive only/);
  assert.match(page, /Comparison thresholds await human approval/);
  assert.match(page, /comparison eligibility is blocked/);
  assert.match(page, /Human-approved descriptive gate/);
  assert.match(page, /represented result states per cohort/);
  assert.match(page, /threshold_contract_version/);
  assert.match(page, /Result-state coverage/);
  assert.match(page, /Outcome evidence gap/);
  assert.match(page, /Result-state gap/);
  assert.match(page, /not instructions to create Outcomes or advance the lifecycle/);
  assert.match(client, /schema_version: "outcome-cohort-evidence-gap\.v1"/);
  assert.match(client, /outcome_creation_authorized: false/);
  assert.match(client, /lifecycle_continuation_authorized: false/);
  assert.match(client, /schema_version: "outcome-cohort-descriptive-comparison\.v1"/);
  assert.match(client, /preferred_alternative_selected: false/);
  assert.match(client, /statistical_significance_estimated: false/);
  assert.match(page, /Cohort comparison contract unavailable/);
  assert.match(page, /Cohort comparison unavailable/);
  assert.match(page, /Eligible Outcome cohort comparison/);
  assert.match(page, /Side-by-side descriptive status mix and effect ranges/);
  assert.match(page, /This view produces no ranking, preferred alternative, causal superiority, statistical significance, or Action recommendation/);
  assert.match(client, /schema_version: "outcome-cohort-comparison-provenance\.v1"/);
  assert.match(client, /binding_source: "IMMUTABLE_ACTION_PROPOSAL"/);
  assert.match(client, /action_identifiers_exposed: false/);
  assert.match(client, /outcome_identifiers_exposed: false/);
  assert.match(client, /shipment_identifiers_exposed: false/);
  assert.match(page, /View comparison provenance/);
  assert.match(page, /Aggregate only—none exposed/);
  assert.match(client, /schema_version: "outcome-cohort-comparison-fingerprint\.v1"/);
  assert.match(client, /canonicalization: "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS"/);
  assert.match(client, /verification_scope: "RESPONSE_CONTENT_INTEGRITY_ONLY"/);
  assert.match(client, /digital_signature: false/);
  assert.match(client, /source_authenticity_attested: false/);
  const fingerprintVerifier = await readFile(new URL("../app/outcome-comparison-fingerprint.ts", import.meta.url), "utf8");
  assert.match(fingerprintVerifier, /globalThis\.crypto\.subtle\.digest/);
  assert.match(fingerprintVerifier, /reason_code: "CRYPTO_UNAVAILABLE"/);
  assert.match(fingerprintVerifier, /reason_code: "VERIFICATION_ERROR"/);
  assert.match(fingerprintVerifier, /status: "VERIFIED"; reason_code: "MATCH"/);
  assert.match(fingerprintVerifier, /status: "MISMATCH";[\s\S]*Exclude<OutcomeComparisonFingerprintReason, "MATCH">/);
  assert.match(page, /Fingerprint verified/);
  assert.match(page, /Comparison metrics and provenance remain hidden until browser verification completes/);
  assert.match(page, /comparisonFingerprintDiagnostic/);
  assert.match(page, /Comparison metrics and provenance are withheld/);
  assert.match(page, /comparison-diagnostic-code/);
  assert.match(fingerprintVerifier, /RETRYABLE_REASON_CODES/);
  assert.match(page, /retryFingerprintVerification/);
  assert.match(page, /Retry local verification/);
  assert.match(page, /browser-only check without requesting new data/);
  assert.match(page, /delete results\[verificationKey\]/);
  assert.match(page, /attempts >= 1/);
  assert.match(page, /retry_attempts: { \.\.\.current\.retry_attempts, \[verificationKey\]: 1 }/);
  assert.match(page, /fingerprintVerification\.view === comparisonView/);
  assert.match(page, /Integrity algorithm/);
  assert.match(page, /Deterministic content fingerprint only—not a digital signature, source-authenticity attestation, or business-validity proof/);
  assert.match(page, /title="Pipeline Health"/);
  assert.match(page, /id: "system", label: "System"/);
  assert.match(page, /title="AWS System & Evidence"/);
  assert.match(page, /Read-only AWS system evidence/);
  assert.match(page, /loadSystemEvidenceSnapshot/);
  assert.match(page, /Snapshot unavailable — status details withheld/);
  assert.match(page, /The snapshot failed validation, so no service status is substituted from page code/);
  assert.match(page, /Repository architecture verified for display/);
  assert.match(page, /type SystemSection = "flow" \| "aws" \| "data" \| "logic" \| "ops" \| "release"/);
  assert.match(page, /Daily E2E Flow/);
  assert.match(page, /AWS Overview/);
  assert.match(page, /Data Catalog/);
  assert.match(page, /Logic & SQL/);
  assert.match(page, /OPS Dashboard/);
  assert.match(page, /Release & Lineage/);
  assert.match(page, /Historical counts intentionally withheld/);
  assert.match(page, /legacy v1 anomaly, root-cause, and decision tables remain implementation history/);
  assert.match(page, /This page performs no AWS inspection/);
  assert.match(page, /Open Pipeline Health/);
  assert.match(page, /Open Forecast Accuracy/);
  assert.match(page, /Open Action Board/);
  assert.match(page, /production aliases, schedules, infrastructure changes, Action mutations, policy activation, and model promotion remain separately human-owned/);
  assert.match(page, /System walkthrough/);
  assert.match(page, /No live health status is exposed/);
  assert.match(page, /Live stages shown/);
  assert.match(page, /This public walkthrough never labels an illustrative stage as healthy/);
  assert.match(page, /Open recovery runbook/);
  assert.match(page, /Future simulations cannot be presented as current pipeline health/);
  assert.match(page, /title="Forecast Accuracy"/);
  assert.match(page, /Readiness logic, not measured performance/);
  assert.match(page, /History gate/);
  assert.match(page, /No forecast points, accuracy scores, or production predictions are presented as observed results/);
  assert.match(page, /Model promotion remains blocked/);
  assert.match(page, /future points remain unobserved projections/);
  assert.match(page, /title="Network Drill-down"/);
  assert.match(page, /shipment identifiers require an operator, approver, or administrator role/);
  assert.match(page, /Costs, raw port identifiers, infrastructure identifiers, and future simulations are excluded/);
  assert.match(page, /type DataStateKind = "loading" \| "empty" \| "stale" \| "partial" \| "failed"/);
  assert.match(page, /aria-live=\{failed \? "assertive" : "polite"\}/);
  assert.match(page, /aria-busy=\{kind === "loading"\}/);
  assert.match(page, /Pipeline evidence is stale/);
  assert.match(page, /Forecast evidence is incomplete/);
  assert.match(page, /Some shipment evidence is still available/);
  assert.match(page, /Assign &amp; edit/);
  assert.match(page, /item\.status === "EDITED"/);
  assert.match(page, /const succeeded = await submitOperation/);
  assert.match(page, /reviewEvidence = async \(actionId: string, forceRefresh = false\)/);
  assert.match(page, /!forceRefresh && selectedEvidence === actionId/);
  assert.match(page, /succeeded && selectedEvidence === action\.action_id/);
  assert.match(page, /await reviewEvidence\(action\.action_id, true\)/);
  assert.match(page, /Action–Outcome evidence chain/);
  assert.match(page, /Read-only lifecycle preview/);
  assert.match(page, /Review illustrative brief/);
  assert.match(page, /aria-label=\{navigationLabel\(item\)\}/);
  assert.match(page, /<i aria-hidden="true">\{item\.icon\}<\/i>/);
  assert.doesNotMatch(page, /Public demonstration mode is read-only\. Configure the internal Operations API and sign in to use the Action Board/);
  assert.match(page, /The proposal is immutable and audit events are append-only/);
  assert.match(page, /never real logistics performance/);
  assert.match(page, /title="Learning Review"/);
  assert.match(page, /Learning evidence is not yet eligible/);
  assert.match(page, /Policy activation always requires a separate named-human approval/);
  assert.match(page, /synthetic policy-review evidence only/);
  assert.match(page, /deterministic safety rules remain in force/);
  assert.match(page, /title="Provider Label Readiness"/);
  assert.match(page, /Supervised evaluation remains blocked/);
  assert.match(page, /Pending labels and future simulations never count/);
  assert.match(page, /model training, model promotion, deployment, recurring prediction, and production readiness remain unauthorized/);
  assert.match(page, /Try again/);

  const operationsCss = await readFile(new URL("../app/operations.css", import.meta.url), "utf8");
  assert.match(operationsCss, /\.data-state\.loading/);
  assert.match(operationsCss, /\.system-section-nav/);
  assert.match(operationsCss, /\.system-evidence-status\.connected/);
  assert.match(operationsCss, /\.system-evidence-status\.failed/);
  assert.match(operationsCss, /\.system-flow-list/);
  assert.match(operationsCss, /\.system-service-grid/);
  assert.match(operationsCss, /\.system-domain-grid/);
  assert.match(operationsCss, /\.system-release-flow/);
  assert.match(operationsCss, /\.data-state\.stale, \.data-state\.partial/);
  assert.match(operationsCss, /\.data-state\.failed/);
  assert.match(operationsCss, /prefers-reduced-motion: reduce/);
  assert.match(operationsCss, /\.action-evidence-flow/);
  assert.match(operationsCss, /\.review-handoff-banner/);
  assert.match(operationsCss, /\.learning-proposal/);
  assert.match(operationsCss, /\.label-readiness-grid/);
  assert.match(operationsCss, /\.label-targets/);
});
