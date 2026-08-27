import type { OperationsAction } from "./operations-api";

export const decisionSeverityFilters = [
  "ALL",
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
] as const;

export type DecisionSeverityFilter = typeof decisionSeverityFilters[number];

export function waitingDecisionActions(
  actions: OperationsAction[],
): OperationsAction[] {
  return actions.filter(
    (action) => action.status === "PROPOSED" || action.status === "EDITED",
  );
}

export function filterDecisionQueue(
  actions: OperationsAction[],
  severity: DecisionSeverityFilter,
): OperationsAction[] {
  const waiting = waitingDecisionActions(actions);
  if (severity === "ALL") return waiting;
  return waiting.filter(
    (action) => action.alert_severity.trim().toUpperCase() === severity,
  );
}

export function decisionSeverityCount(
  actions: OperationsAction[],
  severity: DecisionSeverityFilter,
): number {
  return filterDecisionQueue(actions, severity).length;
}
