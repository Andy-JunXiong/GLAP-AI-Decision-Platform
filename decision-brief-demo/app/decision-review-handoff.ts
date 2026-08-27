import type {
  DecisionBriefV1,
  OperationsAction,
  OperationsRisk,
} from "./operations-api";

export type DecisionReviewHandoffReason =
  | "MISSING_RISK"
  | "AMBIGUOUS_RISK"
  | "RISK_NOT_OPEN"
  | "MISSING_DECISION_BRIEF"
  | "ACTION_BINDING_INCOMPLETE"
  | "SOURCE_MISMATCH"
  | "DECISION_BINDING_MISMATCH"
  | "RATIONALE_MISMATCH";

export type DecisionReviewHandoff =
  | { status: "READY"; brief: DecisionBriefV1 }
  | { status: "BLOCKED"; reason_code: DecisionReviewHandoffReason };

export function resolveDecisionReviewHandoff(
  action: OperationsAction,
  risks: OperationsRisk[],
): DecisionReviewHandoff {
  const matchingRisks = risks.filter(
    (risk) => risk.alert_fingerprint === action.alert_fingerprint,
  );
  if (matchingRisks.length === 0) {
    return { status: "BLOCKED", reason_code: "MISSING_RISK" };
  }
  if (matchingRisks.length !== 1) {
    return { status: "BLOCKED", reason_code: "AMBIGUOUS_RISK" };
  }

  const risk = matchingRisks[0];
  if (risk.status !== "OPEN") {
    return { status: "BLOCKED", reason_code: "RISK_NOT_OPEN" };
  }
  if (!risk.decision_brief) {
    return { status: "BLOCKED", reason_code: "MISSING_DECISION_BRIEF" };
  }
  if (
    !action.decision_brief_version
    || !action.selected_alternative
    || !action.selection_rationale
  ) {
    return { status: "BLOCKED", reason_code: "ACTION_BINDING_INCOMPLETE" };
  }
  if (
    risk.shipment_id !== action.shipment_id
    || risk.alert_type !== action.alert_type
    || risk.decision_brief.decision_type !== action.alert_type
  ) {
    return { status: "BLOCKED", reason_code: "SOURCE_MISMATCH" };
  }
  if (
    risk.decision_brief.schema_version !== action.decision_brief_version
    || risk.decision_brief.recommendation.action_type !== action.action_type
    || risk.decision_brief.recommendation.action_type !== action.selected_alternative
  ) {
    return { status: "BLOCKED", reason_code: "DECISION_BINDING_MISMATCH" };
  }
  if (risk.decision_brief.recommendation.rationale !== action.selection_rationale) {
    return { status: "BLOCKED", reason_code: "RATIONALE_MISMATCH" };
  }
  return { status: "READY", brief: risk.decision_brief };
}

export function decisionReviewHandoffMessage(
  reason: DecisionReviewHandoffReason,
): string {
  const messages: Record<DecisionReviewHandoffReason, string> = {
    MISSING_RISK: "The selected Action has no current matching Risk evidence.",
    AMBIGUOUS_RISK: "The selected Action matches more than one Risk record.",
    RISK_NOT_OPEN: "The selected Action is bound to Risk evidence that is no longer open.",
    MISSING_DECISION_BRIEF: "The selected Action has no complete Decision Brief response.",
    ACTION_BINDING_INCOMPLETE: "The selected Action has an incomplete immutable Decision binding.",
    SOURCE_MISMATCH: "The selected Action and Risk source fields do not reconcile.",
    DECISION_BINDING_MISMATCH: "The selected Action and Decision Brief binding do not match.",
    RATIONALE_MISMATCH: "The selected Action and Decision Brief rationale do not match.",
  };
  return `${messages[reason]} Human review remains blocked and no Action was changed.`;
}
