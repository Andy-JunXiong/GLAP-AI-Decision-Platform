export const DIMENSION_IDS = [
  "evidence_grounding",
  "risk_detection_and_proportionality",
  "policy_compliance",
  "actionability",
  "authority_compliance",
] as const;

export type DimensionId = (typeof DIMENSION_IDS)[number];
export type Locale = "zh" | "en";
export type Preference = "OPTION_A" | "OPTION_B" | "TIE";
export type Scores = Record<DimensionId, number | null>;

export type ReviewAnswer = {
  reviewId: string;
  packageDigest: string;
  optionA: Scores;
  optionB: Scores;
  preferred: Preference | null;
  confidence: number | null;
  notes: string;
};

export type ComparativeJudgments = Record<DimensionId, Preference | null>;

export type StoryReviewAnswer = {
  reviewId: string;
  packageDigest: string;
  judgments: ComparativeJudgments;
  preferred: Preference | null;
  confidence: number | null;
  notes: string;
};

export type DecisionCitation = {
  evidence_id: string;
  fact_ids: string[];
  why_relevant: string;
};

export type SolutionHorizon = {
  horizon: string;
  objective: string;
  steps: string[];
};

export type IntendedBenefit = {
  benefit: string;
  measurement_signal: string;
  claim_status: "EXPECTED_NOT_OBSERVED";
};

export type ScenarioBrief = {
  story_summary: string;
  decision_pressure: string;
  difficulty_points: string[];
  downstream_risks: string[];
  decision_question: string;
  fact_boundary: string;
};

export type DecisionContent = {
  contract_version: "decision-option-contract.v3";
  decision_basis: {
    summary: string;
    evidence_citations: DecisionCitation[];
    strongest_visible_severity: string;
  };
  risk_assessment: {
    risk_level: string;
    risk_statement: string;
    exposure_statement: string;
  };
  problem_response: {
    primary_problem: string;
    difficulty_points: string[];
    impact_pathways: string[];
  };
  action_plan: {
    objective: string;
    steps: Array<{
      sequence: number;
      instruction: string;
      timing: string;
      owner_boundary: string;
    }>;
    review_trigger: string;
  };
  solution_horizons: {
    immediate: SolutionHorizon;
    short_term: SolutionHorizon;
    long_term: SolutionHorizon;
  };
  intended_benefits: {
    short_term: IntendedBenefit[];
    long_term: IntendedBenefit[];
  };
  tradeoffs_and_uncertainty: string[];
  authority_boundary: {
    proposal_only: boolean;
    human_approval_required: boolean;
    permitted_actions: string[];
    prohibited_actions: string[];
  };
};

export type LocalizedDecisionContent = {
  decision_basis: { summary: string; evidence_citations: DecisionCitation[] };
  risk_assessment: { risk_statement: string; exposure_statement: string };
  problem_response: {
    primary_problem: string;
    difficulty_points: string[];
    impact_pathways: string[];
  };
  action_plan: {
    objective: string;
    steps: Array<{ sequence: number; instruction: string }>;
    review_trigger: string;
  };
  solution_horizons: {
    immediate: SolutionHorizon;
    short_term: SolutionHorizon;
    long_term: SolutionHorizon;
  };
  intended_benefits: {
    short_term: IntendedBenefit[];
    long_term: IntendedBenefit[];
  };
  tradeoffs_and_uncertainty: string[];
};

export type ReviewPackage = {
  review_id: string;
  package_digest: string;
  scenario: {
    scenario_title: string;
    scenario_title_zh?: string;
    cutoff_id: string;
    cutoff_at: string;
    scenario_mode: string;
    evidence_classification: string;
    scenario_profile: {
      disruption_type: string;
      region: string;
      transport_mode: string;
      severity_band: string;
    };
    story_profile?: {
      id: string;
      shortTitle: { zh: string; en: string };
      role: { zh: string; en: string };
      regionLabel: { zh: string; en: string };
      disruptionLabel: { zh: string; en: string };
      decisionLens: { zh: string; en: string };
      dependency: { zh: string; en: string };
      statuses: Array<{ zh: string; en: string }>;
      questions: Array<{ zh: string; en: string }>;
      noEvidence: { zh: string; en: string };
      monitorTitle: { zh: string; en: string };
      mitigationTitle: { zh: string; en: string };
    };
    operational_state: {
      as_of_at: string;
      state_provenance: string;
      shipment_scope: string;
      exposed_to_disruption_node: boolean;
      inventory_cover_days: number;
      sla_criticality: string;
      alternate_capacity_available: boolean;
    };
    brief: ScenarioBrief;
    brief_zh?: ScenarioBrief;
    visible_evidence: Array<{
      evidence_id: string;
      evidence_type: string;
      published_at: string;
      available_at: string;
      revision_label: string;
      facts: Array<{
        fact_id: string;
        fact_type: string;
        summary: string;
        summary_zh?: string;
        signal_type: string;
        severity: string;
      }>;
    }>;
  };
  decision_policy: {
    allowed_recommendations: string[];
    high_impact_action_requires_human_review: boolean;
    execution_authority: string;
    outcome_claim_allowed: boolean;
  };
  options: Array<{
    option_id: "OPTION_A" | "OPTION_B";
    recommendation: string;
    priority: string;
    human_review_required: boolean;
    rationale: string;
    content: DecisionContent;
    content_zh?: LocalizedDecisionContent;
    status: string;
  }>;
};

export type RubricDimension = {
  id: DimensionId;
  weight: number;
  question: string;
  anchors: Record<string, string>;
};

export type ReviewBootstrap = {
  bundleId: string;
  bundleDigest: string;
  reviewSchemaVersion: "decision-quality-comparative-review.v1";
  packages: ReviewPackage[];
  dimensions: RubricDimension[];
};

export function emptyScores(): Scores {
  return {
    evidence_grounding: null,
    risk_detection_and_proportionality: null,
    policy_compliance: null,
    actionability: null,
    authority_compliance: null,
  };
}

export function emptyJudgments(): ComparativeJudgments {
  return {
    evidence_grounding: null,
    risk_detection_and_proportionality: null,
    policy_compliance: null,
    actionability: null,
    authority_compliance: null,
  };
}

export function emptyStoryAnswer(item: ReviewPackage): StoryReviewAnswer {
  return {
    reviewId: item.review_id,
    packageDigest: item.package_digest,
    judgments: emptyJudgments(),
    preferred: null,
    confidence: null,
    notes: "",
  };
}

export function isStoryComplete(answer: StoryReviewAnswer): boolean {
  return (
    DIMENSION_IDS.every((id) => answer.judgments[id] !== null) &&
    answer.preferred !== null &&
    answer.confidence !== null
  );
}

export function emptyAnswer(item: ReviewPackage): ReviewAnswer {
  return {
    reviewId: item.review_id,
    packageDigest: item.package_digest,
    optionA: emptyScores(),
    optionB: emptyScores(),
    preferred: null,
    confidence: null,
    notes: "",
  };
}

export function isComplete(answer: ReviewAnswer): boolean {
  return (
    DIMENSION_IDS.every((id) => answer.optionA[id] !== null) &&
    DIMENSION_IDS.every((id) => answer.optionB[id] !== null) &&
    answer.preferred !== null &&
    answer.confidence !== null
  );
}

export function visibleOptionsMatch(item: ReviewPackage): boolean {
  if (item.options.length !== 2) return false;
  const [optionA, optionB] = item.options;
  return (
    optionA.recommendation === optionB.recommendation &&
    optionA.priority === optionB.priority &&
    optionA.human_review_required === optionB.human_review_required &&
    optionA.rationale === optionB.rationale &&
    JSON.stringify(optionA.content) === JSON.stringify(optionB.content)
  );
}
