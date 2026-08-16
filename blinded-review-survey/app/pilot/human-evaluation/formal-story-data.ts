import { visibleOptionsMatch, type ReviewPackage } from "@/lib/review-types";
import type { HeroCase, HeroStage, LocalText, PilotOption } from "../baltimore/hero-case-types";

const l = (zh: string, en: string): LocalText => ({ zh, en });
type StoryProfile = NonNullable<ReviewPackage["scenario"]["story_profile"]>;

export type FormalHeroStage = HeroStage & {
  reviewId: string;
  packageDigest: string;
  sharedPlan: boolean;
  unknown: LocalText;
};
export type FormalHeroCase = Omit<HeroCase, "stages"> & {
  goal: LocalText;
  stakes: LocalText;
  stages: [FormalHeroStage, FormalHeroStage, FormalHeroStage];
};

function cutoffText(value: string): LocalText {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return l(`${year}年${month}月${day}日`, `${day} ${new Date(Date.UTC(year, month - 1, day)).toLocaleString("en", { month: "short", timeZone: "UTC" })} ${year}`);
}

function optionText(item: ReviewPackage, optionIndex: number, profile: StoryProfile, stageIndex: number): PilotOption {
  const source = item.options[optionIndex];
  const isMitigation = source.recommendation === "RISK_MITIGATION";
  return {
    id: optionIndex === 0 ? "A" : "B",
    title: isMitigation ? profile.mitigationTitle : profile.monitorTitle,
    body: isMitigation ? profile.mitigationActions[stageIndex] : profile.monitorActions[stageIndex],
    tradeoff: isMitigation ? profile.mitigationTradeoffs[stageIndex] : profile.monitorTradeoffs[stageIndex],
  };
}

function stageFrom(item: ReviewPackage, profile: StoryProfile, index: number): FormalHeroStage {
  const state = item.scenario.operational_state;
  const options: [PilotOption, PilotOption] = [
    optionText(item, 0, profile, index),
    optionText(item, 1, profile, index),
  ];
  const sharedPlan = visibleOptionsMatch(item);
  if (!sharedPlan && JSON.stringify(options[0]) === JSON.stringify(options[1])) {
    throw new Error(`Distinct frozen options rendered identically for ${item.review_id}`);
  }
  return {
    reviewId: item.review_id,
    packageDigest: item.package_digest,
    moment: (["T0", "T1", "T2"] as const)[index],
    date: cutoffText(item.scenario.cutoff_at),
    status: profile.statuses[index],
    context: profile.storyIntro,
    newEvidence: [profile.updates[index]],
    unknown: profile.unknowns[index],
    sharedPlan,
    operationalFacts: [
      { label: l("你的目标", "Your goal"), value: profile.goal },
      { label: l("时间余量", "Time available"), value: l(`现有库存约能支撑 ${state.inventory_cover_days} 天`, `Current inventory covers about ${state.inventory_cover_days} days`), tone: state.inventory_cover_days <= 7 ? "warning" : undefined },
      { label: l("不能出问题", "What must be protected"), value: profile.stakes, tone: "warning" },
      { label: l("备用办法", "Fallback"), value: state.alternate_capacity_available ? l("有一个备选方向，但价格和时效还没确认", "A fallback exists, but cost and timing are not confirmed") : l("暂时没有现成的备用办法", "No ready fallback is available"), tone: state.alternate_capacity_available ? "positive" : undefined },
    ],
    question: profile.questions[index],
    options,
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
    const threeMomentFields = [
      profile.statuses,
      profile.updates,
      profile.unknowns,
      profile.questions,
      profile.monitorActions,
      profile.monitorTradeoffs,
      profile.mitigationActions,
      profile.mitigationTradeoffs,
    ];
    if (matching.length !== 3 || threeMomentFields.some((field) => field.length !== 3)) {
      throw new Error(`Expected three frozen moments for ${profile.id}`);
    }
    const first = matching[0].scenario.scenario_profile;
    return {
      id: profile.id,
      title: profile.shortTitle,
      shortTitle: profile.shortTitle,
      role: profile.role,
      mode: first.transport_mode as HeroCase["mode"],
      disruption: profile.disruptionLabel,
      region: profile.regionLabel,
      decisionLens: profile.decisionLens,
      goal: profile.goal,
      stakes: profile.stakes,
      stages: matching.map((item, index) => stageFrom(item, profile, index)) as [FormalHeroStage, FormalHeroStage, FormalHeroStage],
    };
  });
}
