import type { ReviewPackage } from "@/lib/review-types";
import type { HeroCase, HeroStage, LocalText, PilotOption } from "../baltimore/hero-case-types";

const l = (zh: string, en: string): LocalText => ({ zh, en });
type StoryProfile = NonNullable<ReviewPackage["scenario"]["story_profile"]>;

export type FormalHeroStage = HeroStage & { reviewId: string; packageDigest: string };
export type FormalHeroCase = Omit<HeroCase, "stages"> & { stages: [FormalHeroStage, FormalHeroStage, FormalHeroStage] };

function cutoffText(value: string): LocalText {
  const display = value.replace("T", " · ");
  return l(display, display);
}

function optionText(item: ReviewPackage, optionIndex: number, profile: StoryProfile): PilotOption {
  const source = item.options[optionIndex];
  const en = source.content;
  const zh = source.content_zh;
  const isMitigation = source.recommendation === "RISK_MITIGATION";
  return {
    id: optionIndex === 0 ? "A" : "B",
    title: isMitigation ? profile.mitigationTitle : profile.monitorTitle,
    body: l(
      (zh?.action_plan.steps ?? []).map((step) => step.instruction).join(" ") || en.action_plan.steps.map((step) => step.instruction).join(" "),
      en.action_plan.steps.map((step) => step.instruction).join(" "),
    ),
    tradeoff: l(
      (zh?.tradeoffs_and_uncertainty ?? en.tradeoffs_and_uncertainty).slice(0, 2).join(" "),
      en.tradeoffs_and_uncertainty.slice(0, 2).join(" "),
    ),
  };
}

function stageFrom(item: ReviewPackage, profile: StoryProfile, index: number, previousFactIds: Set<string>): FormalHeroStage {
  const state = item.scenario.operational_state;
  const briefZh = item.scenario.brief_zh ?? item.scenario.brief;
  const facts = item.scenario.visible_evidence
    .flatMap((evidence) => evidence.facts)
    .filter((fact) => !previousFactIds.has(fact.fact_id));
  const newEvidence = facts.length > 0
    ? facts.map((fact) => l(fact.summary_zh ?? fact.summary, fact.summary))
    : [index === 0
      ? profile.noEvidence
      : l("这个时点没有新增的、可用于决策的事实。", "No additional decision-eligible fact became available at this cutoff.")];
  return {
    reviewId: item.review_id,
    packageDigest: item.package_digest,
    moment: (["T0", "T1", "T2"] as const)[index],
    date: cutoffText(item.scenario.cutoff_at),
    status: profile.statuses[index],
    context: l(`${briefZh.story_summary} ${briefZh.decision_pressure}`, `${item.scenario.brief.story_summary} ${item.scenario.brief.decision_pressure}`),
    newEvidence,
    operationalFacts: [
      { label: l("关键依赖", "Critical dependency"), value: profile.dependency, tone: state.exposed_to_disruption_node ? "warning" : undefined },
      { label: l("库存缓冲", "Inventory buffer"), value: l(`${state.inventory_cover_days} 天`, `${state.inventory_cover_days} days`), tone: state.inventory_cover_days <= 7 ? "warning" : undefined },
      { label: l("服务优先级", "Service priority"), value: l(state.sla_criticality === "HIGH" ? "高" : "中", state.sla_criticality), tone: state.sla_criticality === "HIGH" ? "warning" : undefined },
      { label: l("替代运力", "Alternate capacity"), value: state.alternate_capacity_available ? l("有记录；尚待验证", "Recorded; not yet validated") : l("尚无可用记录", "No available record"), tone: state.alternate_capacity_available ? "positive" : undefined },
    ],
    question: profile.questions[index],
    options: [optionText(item, 0, profile), optionText(item, 1, profile)],
  };
}

export function buildFormalHeroCases(packages: ReviewPackage[]): FormalHeroCase[] {
  const groups = new Map<string, ReviewPackage[]>();
  for (const item of packages) {
    const profile = item.scenario.story_profile;
    if (!profile) throw new Error("Authenticated story profile is missing");
    groups.set(profile.id, [...(groups.get(profile.id) ?? []), item]);
  }
  if (groups.size !== 10) throw new Error(`Expected ten distinct frozen stories; received ${groups.size}`);
  return [...groups.values()].map((group) => {
    const matching = [...group].sort(
      (left, right) => new Date(left.scenario.cutoff_at).getTime() - new Date(right.scenario.cutoff_at).getTime(),
    );
    const profile = matching[0].scenario.story_profile!;
    if (matching.length !== 3 || profile.statuses.length !== 3 || profile.questions.length !== 3) {
      throw new Error(`Expected three frozen moments for ${profile.id}`);
    }
    const first = matching[0].scenario.scenario_profile;
    return {
      id: profile.id,
      title: l(matching[0].scenario.scenario_title_zh ?? matching[0].scenario.scenario_title, matching[0].scenario.scenario_title),
      shortTitle: profile.shortTitle,
      role: profile.role,
      mode: first.transport_mode as HeroCase["mode"],
      disruption: profile.disruptionLabel,
      region: profile.regionLabel,
      decisionLens: profile.decisionLens,
      stages: matching.map((item, index) => {
        const previousFactIds = new Set(
          matching.slice(0, index).flatMap((prior) =>
            prior.scenario.visible_evidence.flatMap((evidence) => evidence.facts.map((fact) => fact.fact_id)),
          ),
        );
        return stageFrom(item, profile, index, previousFactIds);
      }) as [FormalHeroStage, FormalHeroStage, FormalHeroStage],
    };
  });
}
