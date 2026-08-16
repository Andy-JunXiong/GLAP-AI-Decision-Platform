"use client";

import { useEffect, useMemo, useState } from "react";
import { heroCases } from "./hero-case-data";
import type { HeroCase, LocalText } from "./hero-case-types";
import { nextUnlockedStage, timelineNodeView } from "./hero-case-visibility";
import styles from "./baltimore-pilot.module.css";

type Locale = "zh" | "en";
type Choice = "A" | "B" | "TIE";
type QuestionId = "reasonable" | "supported" | "actionable" | "balanced";
type PilotAnswer = Partial<Record<QuestionId, Choice>> & { confidence?: number };
type PilotAnswers = Record<string, Record<number, PilotAnswer>>;
type CommittedThrough = Record<string, number>;
type Screen = "hub" | "case" | "summary";

const STORAGE_KEY = "glap:human-evaluation-pilot:v3";
const PREVIOUS_STORAGE_KEY = "glap:human-evaluation-pilot:v2";
const LEGACY_STORAGE_KEY = "glap:baltimore-human-evaluation-pilot:v1";
const questionIds: QuestionId[] = ["reasonable", "supported", "actionable", "balanced"];

const questions: Array<{ id: QuestionId; label: LocalText }> = [
  { id: "reasonable", label: { zh: "如果你是当班运营负责人，你更愿意采用哪个方案？", en: "If you were the duty operations lead, which plan would you adopt?" } },
  { id: "supported", label: { zh: "哪个方案得到当前证据更好的支持？", en: "Which plan is better supported by the evidence available now?" } },
  { id: "actionable", label: { zh: "哪个方案更容易由团队立即执行？", en: "Which plan can the team execute more readily?" } },
  { id: "balanced", label: { zh: "哪个方案更好地平衡风险、成本与交期？", en: "Which plan better balances risk, cost and delivery commitments?" } },
];

const summaryLabels: Record<QuestionId, LocalText> = {
  reasonable: { zh: "采用方案", en: "Would adopt" },
  supported: { zh: "证据支持", en: "Evidence" },
  actionable: { zh: "可执行性", en: "Actionability" },
  balanced: { zh: "风险与成本", en: "Risk and cost" },
};

function text(value: LocalText, locale: Locale) {
  return value[locale];
}

function isChoice(value: unknown): value is Choice {
  return value === "A" || value === "B" || value === "TIE";
}

function normalizeAnswer(value: unknown): PilotAnswer {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const source = value as Record<string, unknown>;
  const answer: PilotAnswer = {};
  for (const id of questionIds) {
    if (isChoice(source[id])) answer[id] = source[id];
  }
  if (typeof source.confidence === "number" && source.confidence >= 1 && source.confidence <= 5) answer.confidence = source.confidence;
  return answer;
}

function normalizeAnswers(value: unknown): PilotAnswers {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const source = value as Record<string, unknown>;
  const result: PilotAnswers = {};
  for (const heroCase of heroCases) {
    const caseValue = source[heroCase.id];
    if (!caseValue || typeof caseValue !== "object" || Array.isArray(caseValue)) continue;
    const stageSource = caseValue as Record<string, unknown>;
    result[heroCase.id] = {};
    heroCase.stages.forEach((_, index) => { result[heroCase.id][index] = normalizeAnswer(stageSource[index]); });
  }
  return result;
}

function normalizeLegacyAnswers(value: unknown): PilotAnswers {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const source = value as Record<string, unknown>;
  const baltimore: Record<number, PilotAnswer> = {};
  heroCases[0].stages.forEach((_, index) => { baltimore[index] = normalizeAnswer(source[index]); });
  return { [heroCases[0].id]: baltimore };
}

function answerComplete(answer: PilotAnswer | undefined) {
  return Boolean(answer?.confidence && questionIds.every((id) => answer[id]));
}

function normalizeCommittedThrough(value: unknown): CommittedThrough {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const source = value as Record<string, unknown>;
  const result: CommittedThrough = {};
  for (const heroCase of heroCases) {
    const committed = source[heroCase.id];
    if (typeof committed === "number" && Number.isInteger(committed) && committed >= -1 && committed <= 2) result[heroCase.id] = committed;
  }
  return result;
}

function inferCommittedThrough(answers: PilotAnswers): CommittedThrough {
  const result: CommittedThrough = {};
  for (const heroCase of heroCases) {
    let committed = -1;
    for (let index = 0; index < heroCase.stages.length; index += 1) {
      if (!answerComplete(answers[heroCase.id]?.[index])) break;
      committed = index;
    }
    result[heroCase.id] = committed;
  }
  return result;
}

function caseProgress(heroCase: HeroCase, committedThrough: CommittedThrough) {
  return Math.max(0, (committedThrough[heroCase.id] ?? -1) + 1);
}

function ModeBadge({ mode }: { mode: HeroCase["mode"] }) {
  const icon = mode === "OCEAN" ? "≈" : mode === "AIR" ? "↗" : "→";
  return <span className={styles.modeBadge}>{icon} {mode}</span>;
}

export default function BaltimorePilot() {
  const [locale, setLocale] = useState<Locale>("zh");
  const [answers, setAnswers] = useState<PilotAnswers>({});
  const [committedThrough, setCommittedThrough] = useState<CommittedThrough>({});
  const [activeCaseId, setActiveCaseId] = useState(heroCases[0].id);
  const [activeStageIndex, setActiveStageIndex] = useState(0);
  const [screen, setScreen] = useState<Screen>("hub");
  const [storageReady, setStorageReady] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as Record<string, unknown>;
          const restoredAnswers = normalizeAnswers(parsed.answers);
          const restoredCommitted = normalizeCommittedThrough(parsed.committedThrough);
          const restoredCaseId = typeof parsed.activeCaseId === "string" && heroCases.some((item) => item.id === parsed.activeCaseId) ? parsed.activeCaseId : heroCases[0].id;
          const restoredIndex = typeof parsed.activeStageIndex === "number" && parsed.activeStageIndex >= 0 && parsed.activeStageIndex <= 2 ? parsed.activeStageIndex : 0;
          setAnswers(restoredAnswers);
          setCommittedThrough(restoredCommitted);
          if (parsed.locale === "zh" || parsed.locale === "en") setLocale(parsed.locale);
          setActiveCaseId(restoredCaseId);
          setActiveStageIndex(Math.min(restoredIndex, nextUnlockedStage(restoredCommitted[restoredCaseId] ?? -1)));
        } else {
          const previous = window.localStorage.getItem(PREVIOUS_STORAGE_KEY);
          const legacy = previous ?? window.localStorage.getItem(LEGACY_STORAGE_KEY);
          if (legacy) {
            const parsed = JSON.parse(legacy) as Record<string, unknown>;
            const restoredAnswers = previous ? normalizeAnswers(parsed.answers) : normalizeLegacyAnswers(parsed.answers);
            setAnswers(restoredAnswers);
            setCommittedThrough(inferCommittedThrough(restoredAnswers));
          }
        }
      } catch {
        // A damaged local draft must never block a reviewer from opening the pilot.
      } finally {
        setStorageReady(true);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!storageReady) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 3, locale, activeCaseId, activeStageIndex, answers, committedThrough }));
  }, [activeCaseId, activeStageIndex, answers, committedThrough, locale, storageReady]);

  const activeCase = useMemo(() => heroCases.find((item) => item.id === activeCaseId) ?? heroCases[0], [activeCaseId]);
  const stage = activeCase.stages[activeStageIndex];
  const currentAnswer = answers[activeCase.id]?.[activeStageIndex] ?? {};
  const currentComplete = answerComplete(currentAnswer);
  const activeCommittedThrough = committedThrough[activeCase.id] ?? -1;
  const viewingPast = activeStageIndex <= activeCommittedThrough;
  const totalComplete = heroCases.reduce((total, item) => total + caseProgress(item, committedThrough), 0);
  const completedCases = heroCases.filter((item) => caseProgress(item, committedThrough) === item.stages.length).length;

  function updateAnswer(patch: PilotAnswer) {
    if (viewingPast) return;
    setAnswers((previous) => ({ ...previous, [activeCase.id]: { ...(previous[activeCase.id] ?? {}), [activeStageIndex]: { ...(previous[activeCase.id]?.[activeStageIndex] ?? {}), ...patch } } }));
  }

  function openCase(heroCase: HeroCase) {
    const progress = caseProgress(heroCase, committedThrough);
    setActiveCaseId(heroCase.id);
    if (progress === heroCase.stages.length) {
      setActiveStageIndex(0);
      setScreen("summary");
      return;
    }
    setActiveStageIndex(nextUnlockedStage(committedThrough[heroCase.id] ?? -1));
    setScreen("case");
  }

  function commitCurrentStage() {
    if (!currentComplete || viewingPast) return;
    setCommittedThrough((previous) => ({ ...previous, [activeCase.id]: Math.max(previous[activeCase.id] ?? -1, activeStageIndex) }));
    if (activeStageIndex === 2) setScreen("summary");
    else setActiveStageIndex(activeStageIndex + 1);
  }

  function clearLocalResults() {
    window.localStorage.removeItem(STORAGE_KEY);
    window.localStorage.removeItem(PREVIOUS_STORAGE_KEY);
    window.localStorage.removeItem(LEGACY_STORAGE_KEY);
    setAnswers({});
    setCommittedThrough({});
    setActiveCaseId(heroCases[0].id);
    setActiveStageIndex(0);
    setScreen("hub");
  }

  if (!storageReady) return <main className={styles.loading}>{locale === "zh" ? "正在恢复本地进度…" : "Restoring local progress…"}</main>;

  if (screen === "hub") {
    return (
      <main className={styles.shell}>
        <Header locale={locale} onLocale={() => setLocale(locale === "zh" ? "en" : "zh")} />
        <section className={styles.hub}>
          <div className={styles.hubIntro}>
            <p className={styles.kicker}>{locale === "zh" ? "Human Evaluation · 5 个真实决策故事" : "Human Evaluation · 5 operational decision stories"}</p>
            <h1>{locale === "zh" ? "在信息逐步出现时，做一次真实的运营判断" : "Make real operational judgments as evidence unfolds"}</h1>
            <p>{locale === "zh" ? "每个案例包含三个决策时点。你只会看到该时点已经出现的信息，以及两个匿名、可执行的选择。" : "Each case has three decision moments. You only see information available at that moment and two anonymous, executable choices."}</p>
            <div className={styles.hubStats}>
              <div><strong>{completedCases}/5</strong><span>{locale === "zh" ? "已完成案例" : "cases complete"}</span></div>
              <div><strong>{totalComplete}/15</strong><span>{locale === "zh" ? "已完成判断" : "judgments complete"}</span></div>
              <div><strong>{Math.round((totalComplete / 15) * 100)}%</strong><span>{locale === "zh" ? "整体进度" : "overall progress"}</span></div>
            </div>
          </div>
          <div className={styles.caseGrid}>
            {heroCases.map((heroCase, index) => {
              const progress = caseProgress(heroCase, committedThrough);
              return <article className={styles.caseCard} key={heroCase.id}>
                <header><span className={styles.caseNumber}>{String(index + 1).padStart(2, "0")}</span><ModeBadge mode={heroCase.mode} /></header>
                <div className={styles.caseMeta}>{text(heroCase.region, locale)} · {text(heroCase.disruption, locale)}</div>
                <h2>{text(heroCase.shortTitle, locale)}</h2><p>{text(heroCase.role, locale)}</p>
                <div className={styles.decisionLens}><small>{locale === "zh" ? "决策焦点" : "Decision focus"}</small><strong>{text(heroCase.decisionLens, locale)}</strong></div>
                <div className={styles.caseProgress}><span><i style={{ width: `${(progress / 3) * 100}%` }} /></span><small>{progress}/3 {locale === "zh" ? "个时点" : "moments"}</small></div>
                <button type="button" onClick={() => openCase(heroCase)}>{progress === 3 ? (locale === "zh" ? "查看结果" : "View results") : progress > 0 ? (locale === "zh" ? "继续评审" : "Continue review") : (locale === "zh" ? "开始案例" : "Start case")}</button>
              </article>;
            })}
          </div>
          <div className={styles.hubFooter}>
            <p>{locale === "zh" ? "答案只保存在当前浏览器，不会提交，也不会计入 Decision Quality 证据。" : "Answers stay in this browser only. They are not submitted or counted as Decision Quality evidence."}</p>
            {totalComplete > 0 && <button type="button" onClick={clearLocalResults}>{locale === "zh" ? "清除全部本地结果" : "Clear all local results"}</button>}
          </div>
        </section>
      </main>
    );
  }

  if (screen === "summary") {
    return (
      <main className={styles.shell}>
        <Header locale={locale} onLocale={() => setLocale(locale === "zh" ? "en" : "zh")} />
        <section className={styles.finish}>
          <button className={styles.backButton} type="button" onClick={() => setScreen("hub")}>← {locale === "zh" ? "全部案例" : "All cases"}</button>
          <p className={styles.kicker}>{text(activeCase.shortTitle, locale)} · {locale === "zh" ? "本地评审结果" : "Local review result"}</p>
          <div className={styles.finishMark}>✓</div><h1>{locale === "zh" ? "这个决策故事已完成" : "This decision story is complete"}</h1>
          <p>{locale === "zh" ? "下面汇总你在三个时点的判断。结果只保存在当前浏览器中。" : "Your judgments across all three moments are summarized below. Results remain in this browser only."}</p>
          <div className={styles.resultGrid}>
            {activeCase.stages.map((resultStage, index) => {
              const result = answers[activeCase.id]?.[index] ?? {};
              return <article className={styles.resultCard} key={resultStage.moment}>
                <header><span>{resultStage.moment}</span><div><strong>{text(resultStage.status, locale)}</strong><small>{text(resultStage.date, locale)}</small></div></header>
                <dl>{questionIds.map((id) => <div key={id}><dt>{text(summaryLabels[id], locale)}</dt><dd>{result[id] ?? "—"}</dd></div>)}</dl>
                <footer><span>{locale === "zh" ? "信心" : "Confidence"}: {result.confidence ?? "—"}/5</span><button type="button" onClick={() => { setActiveStageIndex(index); setScreen("case"); }}>{locale === "zh" ? "查看" : "View"}</button></footer>
              </article>;
            })}
          </div>
          <button className={styles.restartButton} type="button" onClick={() => setScreen("hub")}>{locale === "zh" ? "返回五个案例" : "Return to all cases"}</button>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.shell}>
      <Header locale={locale} onLocale={() => setLocale(locale === "zh" ? "en" : "zh")} />
      <div className={styles.layout}>
        <aside className={styles.timeline}>
          <button className={styles.backButton} type="button" onClick={() => setScreen("hub")}>← {locale === "zh" ? "全部案例" : "All cases"}</button>
          <p className={styles.kicker}>{text(activeCase.region, locale)} · {activeCase.mode}</p><h1>{text(activeCase.shortTitle, locale)}</h1>
          <p className={styles.role}>{locale === "zh" ? "你的角色" : "Your role"}<strong>{text(activeCase.role, locale)}</strong></p>
          <div className={styles.sidebarLens}><small>{locale === "zh" ? "本案例考察" : "This case examines"}</small><strong>{text(activeCase.decisionLens, locale)}</strong></div>
          <nav aria-label={locale === "zh" ? "决策时点" : "Decision moments"}>{activeCase.stages.map((item, index) => {
            const node = timelineNodeView(item, index, activeCommittedThrough, locale);
            const className = [index === activeStageIndex ? styles.activeMoment : "", node.disabled ? styles.futureMoment : "", node.isPast ? styles.pastMoment : ""].filter(Boolean).join(" ");
            return <button key={item.moment} type="button" className={className} aria-label={node.ariaLabel} disabled={node.disabled} onClick={() => setActiveStageIndex(index)}><i>{node.isPast ? "✓" : item.moment}</i><span>{node.disabled ? <strong>{locale === "zh" ? "未解锁" : "Locked"}</strong> : <><strong>{node.status}</strong><small>{node.date}</small></>}</span></button>;
          })}</nav>
          <div className={styles.dataBoundary}>{locale === "zh" ? "只根据这个时点已出现的信息判断。后续事实不会提前显示。" : "Judge only from information available at this moment. Later facts are not shown early."}</div>
          <div className={styles.progress}><span><i style={{ width: `${(caseProgress(activeCase, committedThrough) / 3) * 100}%` }} /></span><small>{caseProgress(activeCase, committedThrough)}/3 {locale === "zh" ? "已提交并保存在本机" : "committed and saved locally"}</small></div>
        </aside>
        <section className={styles.content}>
          <div className={styles.decisionTime}><span>{stage.moment}</span><div><small>{locale === "zh" ? "当前决策时间" : "Current decision time"}</small><strong>{text(stage.date, locale)}</strong></div><em>{text(stage.status, locale)}</em></div>
          <article className={styles.storyCard}><span className={styles.sectionNumber}>01</span><div><p className={styles.kicker}>{locale === "zh" ? "发生了什么" : "What happened"}</p><h2>{text(activeCase.title, locale)}</h2><p className={styles.storyText}>{text(stage.context, locale)}</p></div></article>
          <div className={styles.factColumns}>
            <section className={styles.factPanel}><p className={styles.kicker}>{locale === "zh" ? "此刻新增的信息" : "What is newly known"}</p><ul>{stage.newEvidence.map((item, index) => <li key={index}><span>◆</span>{text(item, locale)}</li>)}</ul></section>
            <section className={styles.factPanel}><p className={styles.kicker}>{locale === "zh" ? "当前运营事实" : "Current operational facts"}</p><dl>{stage.operationalFacts.map((fact) => <div key={fact.label.en}><dt>{text(fact.label, locale)}</dt><dd data-tone={fact.tone}>{text(fact.value, locale)}</dd></div>)}</dl></section>
          </div>
          <div className={styles.questionBanner}><span>?</span><div><small>{locale === "zh" ? "你现在必须决定" : "You must decide now"}</small><h2>{text(stage.question, locale)}</h2></div></div>
          <section className={styles.optionsSection}>
            <div className={styles.sectionHeading}><div><span>02</span><h2>{locale === "zh" ? "两个可执行选择" : "Two executable choices"}</h2></div><small>{locale === "zh" ? "方案来自不同决策流程；身份已隐藏" : "Plans come from different decision processes; identity is hidden"}</small></div>
            <div className={styles.optionGrid}>{stage.options.map((option) => <article className={styles.optionCard} key={option.id}><header><span>{option.id}</span><div><small>{locale === "zh" ? `方案 ${option.id}` : `Plan ${option.id}`}</small><h3>{text(option.title, locale)}</h3></div></header><p>{text(option.body, locale)}</p><footer><strong>{locale === "zh" ? "主要代价 / 风险" : "Main trade-off / risk"}</strong><span>{text(option.tradeoff, locale)}</span></footer></article>)}</div>
          </section>
          <section className={styles.reviewSection}>
            <div className={styles.sectionHeading}><div><span>03</span><h2>{locale === "zh" ? "做出你的判断" : "Make your judgment"}</h2></div><small>{viewingPast ? (locale === "zh" ? "该判断已锁定；揭示后续信息后不能修改" : "This judgment is locked after later evidence was revealed") : (locale === "zh" ? "每题必须选择；提交后将锁定" : "Choose one per question; submission locks the judgment")}</small></div>
            <div className={styles.reviewQuestions}>{questions.map((question, index) => <div className={styles.reviewRow} key={question.id}><div><span>{String(index + 1).padStart(2, "0")}</span><strong>{text(question.label, locale)}</strong></div><div>{(["A", "B", "TIE"] as Choice[]).map((choice) => <button type="button" key={choice} disabled={viewingPast} className={currentAnswer[question.id] === choice ? styles.selected : ""} onClick={() => updateAnswer({ [question.id]: choice })}>{choice === "TIE" ? (locale === "zh" ? "相当" : "Tie") : `${locale === "zh" ? "方案" : "Plan"} ${choice}`}</button>)}</div></div>)}</div>
            <div className={styles.confidence}><div><span>05</span><strong>{locale === "zh" ? "你对这组判断有多大信心？" : "How confident are you in these judgments?"}</strong></div><div>{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} disabled={viewingPast} className={currentAnswer.confidence === value ? styles.selected : ""} onClick={() => updateAnswer({ confidence: value })}>{value}</button>)}</div></div>
          </section>
          <div className={styles.bottomNav}>
            <button type="button" disabled={activeStageIndex === 0} onClick={() => setActiveStageIndex((value) => Math.max(0, value - 1))}>← {locale === "zh" ? "上一个时点" : "Previous moment"}</button>
            <p>{viewingPast ? (locale === "zh" ? "该判断已锁定，只能查看" : "This judgment is locked and view-only") : currentComplete ? (locale === "zh" ? "提交后将揭示下一个时点，并锁定当前判断" : "Submission reveals the next moment and locks this judgment") : (locale === "zh" ? "完成四项判断和信心评分后提交" : "Complete four judgments and confidence before submitting")}</p>
            {viewingPast
              ? <button className={styles.nextButton} type="button" onClick={() => { if (activeCommittedThrough === 2) setScreen("summary"); else setActiveStageIndex(nextUnlockedStage(activeCommittedThrough)); }}>{activeCommittedThrough === 2 ? (locale === "zh" ? "返回结果" : "Return to results") : (locale === "zh" ? "返回当前时点" : "Return to current moment")} →</button>
              : <button className={styles.nextButton} type="button" disabled={!currentComplete} onClick={commitCurrentStage}>{activeStageIndex === 2 ? (locale === "zh" ? "提交并查看结果" : "Submit and view results") : (locale === "zh" ? "提交并进入下一时点" : "Submit and reveal next moment")} →</button>}
          </div>
        </section>
      </div>
    </main>
  );
}

function Header({ locale, onLocale }: { locale: Locale; onLocale: () => void }) {
  return <header className={styles.topbar}><div className={styles.brand}><span>GLAP</span><small>Human Evaluation</small></div><div className={styles.headerMeta}><span>{locale === "zh" ? "体验预览 · 不提交" : "Experience preview · no submission"}</span><button className={styles.localeButton} type="button" onClick={onLocale}>{locale === "zh" ? "EN" : "中文"}</button></div></header>;
}
