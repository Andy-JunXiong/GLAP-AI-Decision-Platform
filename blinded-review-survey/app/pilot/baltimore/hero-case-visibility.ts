import type { HeroStage } from "./hero-case-types";

export type PilotLocale = "zh" | "en";

export type TimelineNodeView = {
  moment: HeroStage["moment"];
  status: string | null;
  date: string | null;
  ariaLabel: string;
  disabled: boolean;
  isPast: boolean;
  isCurrent: boolean;
};

export function nextUnlockedStage(committedThrough: number) {
  return Math.min(Math.max(committedThrough + 1, 0), 2);
}

export function timelineNodeView(
  stage: HeroStage,
  index: number,
  committedThrough: number,
  locale: PilotLocale,
): TimelineNodeView {
  const unlockedIndex = nextUnlockedStage(committedThrough);
  const disabled = index > unlockedIndex;
  const lockedLabel = locale === "zh" ? "未解锁" : "Locked";
  if (disabled) {
    return {
      moment: stage.moment,
      status: null,
      date: null,
      ariaLabel: `${stage.moment} · ${lockedLabel}`,
      disabled: true,
      isPast: false,
      isCurrent: false,
    };
  }

  const status = stage.status[locale];
  const date = stage.date[locale];
  return {
    moment: stage.moment,
    status,
    date,
    ariaLabel: `${stage.moment} · ${status} · ${date}`,
    disabled: false,
    isPast: index <= committedThrough,
    isCurrent: committedThrough < 2 && index === unlockedIndex,
  };
}
