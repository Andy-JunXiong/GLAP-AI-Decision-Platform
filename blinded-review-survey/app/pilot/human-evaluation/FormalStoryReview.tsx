"use client";

import { useMemo, useState } from "react";
import {
  DIMENSION_IDS,
  emptyStoryAnswer,
  isStoryComplete,
  type Locale,
  type Preference,
  type ReviewBootstrap,
  type StoryReviewAnswer,
} from "@/lib/review-types";
import { dimensionZh } from "@/lib/translations";
import styles from "../baltimore/baltimore-pilot.module.css";
import { timelineNodeView } from "../baltimore/hero-case-visibility";
import { buildFormalHeroCases, type FormalHeroCase } from "./formal-story-data";

type Screen = "hub" | "case" | "summary" | "final";
type SaveState = "idle" | "saving" | "saved" | "error";

type Props = {
  bootstrap: ReviewBootstrap;
  locale: Locale;
  answers: Record<string, StoryReviewAnswer>;
  onLocale: (locale: Locale) => void;
  onLogout: () => Promise<void>;
  onCommit: (answer: StoryReviewAnswer) => Promise<boolean>;
  onSubmit: () => Promise<boolean>;
};

const text = (value: { zh: string; en: string }, locale: Locale) => value[locale];

function contiguousProgress(heroCase: FormalHeroCase, answers: Record<string, StoryReviewAnswer>) {
  let committed = -1;
  for (let index = 0; index < heroCase.stages.length; index += 1) {
    const answer = answers[heroCase.stages[index].reviewId];
    if (!answer || !isStoryComplete(answer)) break;
    committed = index;
  }
  return committed;
}

function ModeBadge({ mode }: { mode: FormalHeroCase["mode"] }) {
  const icon = mode === "OCEAN" ? "≈" : mode === "AIR" ? "↗" : mode === "RAIL" ? "⇄" : "→";
  return <span className={styles.modeBadge}>{icon} {mode}</span>;
}

function choiceLabel(choice: Preference, locale: Locale) {
  if (choice === "TIE") return locale === "zh" ? "相当" : "Tie";
  return `${locale === "zh" ? "方案" : "Plan"} ${choice === "OPTION_A" ? "A" : "B"}`;
}

function FormalHeader({ locale, onLocale, onLogout }: Pick<Props, "locale" | "onLocale" | "onLogout">) {
  return (
    <header className={styles.topbar}>
      <div className={styles.brand}><span>GLAP</span><small>Human Evaluation</small></div>
      <div className={styles.headerMeta}>
        <span>{locale === "zh" ? "正式评审 · 服务器保存 · 可提交" : "Formal review · server saved · submits"}</span>
        <button className={styles.localeButton} type="button" onClick={() => onLocale(locale === "zh" ? "en" : "zh")}>{locale === "zh" ? "EN" : "中文"}</button>
        <button className={styles.localeButton} type="button" onClick={() => void onLogout()}>{locale === "zh" ? "退出" : "Sign out"}</button>
      </div>
    </header>
  );
}

export default function FormalStoryReview({ bootstrap, locale, answers, onLocale, onLogout, onCommit, onSubmit }: Props) {
  const heroCases = useMemo(() => buildFormalHeroCases(bootstrap.packages), [bootstrap.packages]);
  const [drafts, setDrafts] = useState<Record<string, StoryReviewAnswer>>(answers);
  const [activeCaseId, setActiveCaseId] = useState(heroCases[0].id);
  const [activeStageIndex, setActiveStageIndex] = useState(0);
  const [screen, setScreen] = useState<Screen>("hub");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [message, setMessage] = useState("");

  const activeCase = heroCases.find((item) => item.id === activeCaseId) ?? heroCases[0];
  const activeCommittedThrough = contiguousProgress(activeCase, answers);
  const stage = activeCase.stages[activeStageIndex];
  const currentAnswer = drafts[stage.reviewId] ?? emptyStoryAnswer(
    bootstrap.packages.find((item) => item.review_id === stage.reviewId)!,
  );
  const viewingPast = Boolean(answers[stage.reviewId] && isStoryComplete(answers[stage.reviewId]));
  const currentComplete = isStoryComplete(currentAnswer);
  const totalComplete = bootstrap.packages.filter((item) => isStoryComplete(answers[item.review_id] ?? emptyStoryAnswer(item))).length;
  const completedCases = heroCases.filter((item) => contiguousProgress(item, answers) === 2).length;

  function caseProgress(heroCase: FormalHeroCase) {
    return Math.max(0, contiguousProgress(heroCase, answers) + 1);
  }

  function updateAnswer(mutator: (answer: StoryReviewAnswer) => StoryReviewAnswer) {
    if (viewingPast || saveState === "saving") return;
    setDrafts((current) => ({ ...current, [stage.reviewId]: mutator(current[stage.reviewId] ?? currentAnswer) }));
    setSaveState("idle");
    setMessage("");
  }

  function openCase(heroCase: FormalHeroCase) {
    const progress = caseProgress(heroCase);
    setActiveCaseId(heroCase.id);
    setActiveStageIndex(progress === 3 ? 0 : progress);
    setScreen(progress === 3 ? "summary" : "case");
    setMessage("");
  }

  async function commitCurrentStage() {
    if (!currentComplete || viewingPast) return;
    setSaveState("saving");
    const saved = await onCommit(currentAnswer);
    if (!saved) {
      setSaveState("error");
      setMessage(locale === "zh" ? "保存失败，请重试。" : "Save failed. Please retry.");
      return;
    }
    setSaveState("saved");
    if (activeStageIndex === 2) setScreen("summary");
    else setActiveStageIndex(activeStageIndex + 1);
  }

  async function submitAll() {
    if (totalComplete !== bootstrap.packages.length) return;
    setSaveState("saving");
    const submitted = await onSubmit();
    if (!submitted) {
      setSaveState("error");
      setMessage(locale === "zh" ? "最终提交失败，请重试。" : "Final submission failed. Please retry.");
    }
  }

  if (screen === "hub") {
    return (
      <main className={styles.shell}>
        <FormalHeader locale={locale} onLocale={onLocale} onLogout={onLogout} />
        <section className={`${styles.hub} ${styles.formalHub}`}>
          <div className={styles.hubIntro}>
            <p className={styles.kicker}>{locale === "zh" ? "FORMAL HUMAN EVALUATION · 10 个不同决策故事" : "FORMAL HUMAN EVALUATION · 10 DISTINCT DECISION STORIES"}</p>
            <h1>{locale === "zh" ? "在信息逐步出现时，做出真正的运营判断" : "Make real operational judgments as evidence unfolds"}</h1>
            <p>{locale === "zh" ? "每个案例有三个按时间解锁的决策时点。每次提交都会保存到服务器并锁定当前判断，后续事实不会提前显示。" : "Each case has three decision moments unlocked in time order. Every committed judgment is saved to the server and locked; later facts are never shown early."}</p>
            <div className={styles.hubStats}>
              <div><strong>{completedCases}/10</strong><span>{locale === "zh" ? "已完成案例" : "cases complete"}</span></div>
              <div><strong>{totalComplete}/30</strong><span>{locale === "zh" ? "已保存判断" : "judgments saved"}</span></div>
              <div><strong>{Math.round((totalComplete / 30) * 100)}%</strong><span>{locale === "zh" ? "整体进度" : "overall progress"}</span></div>
            </div>
          </div>
          <div className={styles.caseGrid}>
            {heroCases.map((heroCase, index) => {
              const progress = caseProgress(heroCase);
              return <article className={styles.caseCard} key={heroCase.id}>
                <header><span className={styles.caseNumber}>{String(index + 1).padStart(2, "0")}</span><ModeBadge mode={heroCase.mode} /></header>
                <div className={styles.caseMeta}>{text(heroCase.region, locale)} · {text(heroCase.disruption, locale)}</div>
                <h2>{text(heroCase.shortTitle, locale)}</h2><p>{text(heroCase.role, locale)}</p>
                <div className={styles.decisionLens}><small>{locale === "zh" ? "独特决策焦点" : "Distinct decision focus"}</small><strong>{text(heroCase.decisionLens, locale)}</strong></div>
                <div className={styles.caseProgress}><span><i style={{ width: `${(progress / 3) * 100}%` }} /></span><small>{progress}/3 {locale === "zh" ? "个时点" : "moments"}</small></div>
                <button type="button" onClick={() => openCase(heroCase)}>{progress === 3 ? (locale === "zh" ? "查看结果" : "View results") : progress > 0 ? (locale === "zh" ? "继续评审" : "Continue review") : (locale === "zh" ? "开始案例" : "Start case")}</button>
              </article>;
            })}
          </div>
          <div className={styles.hubFooter}>
            <p>{locale === "zh" ? "只有完成全部 30 个时点后才能最终提交。旧体验预览的浏览器答案不会迁移。" : "Final submission is available only after all 30 moments are complete. Browser-only preview answers are not migrated."}</p>
            {totalComplete === 30 && <button type="button" onClick={() => setScreen("final")}>{locale === "zh" ? "检查并最终提交" : "Review and submit"}</button>}
          </div>
        </section>
      </main>
    );
  }

  if (screen === "summary") {
    return (
      <main className={styles.shell}>
        <FormalHeader locale={locale} onLocale={onLocale} onLogout={onLogout} />
        <section className={styles.finish}>
          <button className={styles.backButton} type="button" onClick={() => setScreen("hub")}>← {locale === "zh" ? "全部案例" : "All cases"}</button>
          <p className={styles.kicker}>{text(activeCase.shortTitle, locale)} · {locale === "zh" ? "正式评审结果" : "Formal review result"}</p>
          <div className={styles.finishMark}>✓</div><h1>{locale === "zh" ? "这个决策故事已保存" : "This decision story is saved"}</h1>
          <p>{locale === "zh" ? "三个时点的判断已保存在服务器并锁定。" : "Judgments across all three moments are server-saved and locked."}</p>
          <div className={styles.resultGrid}>
            {activeCase.stages.map((resultStage, index) => {
              const result = answers[resultStage.reviewId];
              return <article className={styles.resultCard} key={resultStage.moment}>
                <header><span>{resultStage.moment}</span><div><strong>{text(resultStage.status, locale)}</strong><small>{text(resultStage.date, locale)}</small></div></header>
                <dl>
                  {DIMENSION_IDS.map((id) => <div key={id}><dt>{locale === "zh" ? dimensionZh[id].title : bootstrap.dimensions.find((dimension) => dimension.id === id)?.question}</dt><dd>{result ? choiceLabel(result.judgments[id]!, locale) : "—"}</dd></div>)}
                  <div><dt>{locale === "zh" ? "整体偏好" : "Overall preference"}</dt><dd>{result ? choiceLabel(result.preferred!, locale) : "—"}</dd></div>
                </dl>
                <footer><span>{locale === "zh" ? "信心" : "Confidence"}: {result?.confidence ?? "—"}/5</span><button type="button" onClick={() => { setActiveStageIndex(index); setScreen("case"); }}>{locale === "zh" ? "查看" : "View"}</button></footer>
              </article>;
            })}
          </div>
          <button className={styles.restartButton} type="button" onClick={() => setScreen("hub")}>{locale === "zh" ? "返回十个案例" : "Return to all cases"}</button>
        </section>
      </main>
    );
  }

  if (screen === "final") {
    return (
      <main className={styles.shell}>
        <FormalHeader locale={locale} onLocale={onLocale} onLogout={onLogout} />
        <section className={styles.finish}>
          <button className={styles.backButton} type="button" onClick={() => setScreen("hub")}>← {locale === "zh" ? "返回案例" : "Back to cases"}</button>
          <p className={styles.kicker}>FINAL SUBMISSION</p>
          <div className={styles.finishMark}>30</div>
          <h1>{locale === "zh" ? "全部 10 个案例、30 个时点均已完成" : "All 10 cases and 30 moments are complete"}</h1>
          <p>{locale === "zh" ? "最终提交后整份评审将永久锁定。提交不会执行任何物流操作，也不代表生产就绪。" : "Final submission permanently locks the review. It executes no logistics action and does not establish production readiness."}</p>
          {message && <p>{message}</p>}
          <button className={styles.restartButton} type="button" disabled={saveState === "saving"} onClick={() => void submitAll()}>{saveState === "saving" ? (locale === "zh" ? "正在提交…" : "Submitting…") : (locale === "zh" ? "最终提交正式评审" : "Submit formal review")}</button>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.shell}>
      <FormalHeader locale={locale} onLocale={onLocale} onLogout={onLogout} />
      <div className={styles.layout}>
        <aside className={styles.timeline}>
          <button className={styles.backButton} type="button" onClick={() => setScreen("hub")}>← {locale === "zh" ? "全部案例" : "All cases"}</button>
          <p className={styles.kicker}>{text(activeCase.region, locale)} · {activeCase.mode}</p><h1>{text(activeCase.shortTitle, locale)}</h1>
          <p className={styles.role}>{locale === "zh" ? "你的角色" : "Your role"}<strong>{text(activeCase.role, locale)}</strong></p>
          <div className={styles.sidebarLens}><small>{locale === "zh" ? "本案例独特考察" : "This case uniquely examines"}</small><strong>{text(activeCase.decisionLens, locale)}</strong></div>
          <nav aria-label={locale === "zh" ? "决策时点" : "Decision moments"}>{activeCase.stages.map((item, index) => {
            const node = timelineNodeView(item, index, activeCommittedThrough, locale);
            const className = [index === activeStageIndex ? styles.activeMoment : "", node.disabled ? styles.futureMoment : "", node.isPast ? styles.pastMoment : ""].filter(Boolean).join(" ");
            return <button key={item.moment} type="button" className={className} aria-label={node.ariaLabel} disabled={node.disabled} onClick={() => setActiveStageIndex(index)}><i>{node.isPast ? "✓" : item.moment}</i><span>{node.disabled ? <strong>{locale === "zh" ? "未解锁" : "Locked"}</strong> : <><strong>{node.status}</strong><small>{node.date}</small></>}</span></button>;
          })}</nav>
          <div className={styles.dataBoundary}>{locale === "zh" ? "只根据这个时点已出现的信息判断。后续事实不会提前显示。" : "Judge only from information available at this moment. Later facts are not shown early."}</div>
          <div className={styles.progress}><span><i style={{ width: `${(caseProgress(activeCase) / 3) * 100}%` }} /></span><small>{caseProgress(activeCase)}/3 {locale === "zh" ? "已提交并保存到服务器" : "committed and server-saved"}</small></div>
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
            <div className={styles.sectionHeading}><div><span>02</span><h2>{locale === "zh" ? "两个可执行选择" : "Two executable choices"}</h2></div><small>{locale === "zh" ? "方案身份已隐藏；任何执行仍需具名人员批准" : "Plan identity is hidden; execution still requires named-human approval"}</small></div>
            <div className={styles.optionGrid}>{stage.options.map((option) => <article className={styles.optionCard} key={option.id}><header><span>{option.id}</span><div><small>{locale === "zh" ? `方案 ${option.id}` : `Plan ${option.id}`}</small><h3>{text(option.title, locale)}</h3></div></header><p>{text(option.body, locale)}</p><footer><strong>{locale === "zh" ? "主要代价 / 风险" : "Main trade-off / risk"}</strong><span>{text(option.tradeoff, locale)}</span></footer></article>)}</div>
          </section>
          <section className={styles.reviewSection}>
            <div className={styles.sectionHeading}><div><span>03</span><h2>{locale === "zh" ? "逐项比较两个方案" : "Compare the two plans"}</h2></div><small>{viewingPast ? (locale === "zh" ? "该时点已锁定，只能查看" : "This moment is locked and view-only") : (locale === "zh" ? "每项选择 A、B 或相当；保存后锁定" : "Choose A, B, or Tie for each; saving locks the moment")}</small></div>
            <div className={styles.reviewQuestions}>{DIMENSION_IDS.map((id, index) => {
              const dimension = bootstrap.dimensions.find((item) => item.id === id);
              return <div className={styles.reviewRow} key={id}><div><span>{String(index + 1).padStart(2, "0")}</span><strong>{locale === "zh" ? dimensionZh[id].question : dimension?.question}</strong></div><div>{(["OPTION_A", "OPTION_B", "TIE"] as Preference[]).map((choice) => <button type="button" key={choice} disabled={viewingPast || saveState === "saving"} className={currentAnswer.judgments[id] === choice ? styles.selected : ""} onClick={() => updateAnswer((answer) => ({ ...answer, judgments: { ...answer.judgments, [id]: choice } }))}>{choiceLabel(choice, locale)}</button>)}</div></div>;
            })}
              <div className={styles.reviewRow}><div><span>06</span><strong>{locale === "zh" ? "综合来看，你更愿意采用哪个方案？" : "Overall, which plan would you choose?"}</strong></div><div>{(["OPTION_A", "OPTION_B", "TIE"] as Preference[]).map((choice) => <button type="button" key={choice} disabled={viewingPast || saveState === "saving"} className={currentAnswer.preferred === choice ? styles.selected : ""} onClick={() => updateAnswer((answer) => ({ ...answer, preferred: choice }))}>{choiceLabel(choice, locale)}</button>)}</div></div>
            </div>
            <div className={styles.confidence}><div><span>07</span><strong>{locale === "zh" ? "你对这组判断有多大信心？" : "How confident are you in these judgments?"}</strong></div><div>{[1, 2, 3, 4, 5].map((value) => <button type="button" key={value} disabled={viewingPast || saveState === "saving"} className={currentAnswer.confidence === value ? styles.selected : ""} onClick={() => updateAnswer((answer) => ({ ...answer, confidence: value }))}>{value}</button>)}</div></div>
          </section>
          {message && <p>{message}</p>}
          <div className={styles.bottomNav}>
            <button type="button" disabled={activeStageIndex === 0} onClick={() => setActiveStageIndex((value) => Math.max(0, value - 1))}>← {locale === "zh" ? "上一个时点" : "Previous moment"}</button>
            <p>{viewingPast ? (locale === "zh" ? "该判断已锁定，只能查看" : "This judgment is locked and view-only") : currentComplete ? (locale === "zh" ? "提交后将保存到服务器、锁定当前判断并揭示下一时点" : "Commit saves to the server, locks this judgment, and reveals the next moment") : (locale === "zh" ? "完成五项比较、整体偏好和信心后提交" : "Complete five comparisons, overall preference, and confidence")}</p>
            {viewingPast
              ? <button className={styles.nextButton} type="button" onClick={() => { if (activeCommittedThrough === 2) setScreen("summary"); else setActiveStageIndex(activeCommittedThrough + 1); }}>{activeCommittedThrough === 2 ? (locale === "zh" ? "返回结果" : "Return to results") : (locale === "zh" ? "返回当前时点" : "Return to current moment")} →</button>
              : <button className={styles.nextButton} type="button" disabled={!currentComplete || saveState === "saving"} onClick={() => void commitCurrentStage()}>{saveState === "saving" ? (locale === "zh" ? "正在保存…" : "Saving…") : activeStageIndex === 2 ? (locale === "zh" ? "提交并查看结果" : "Commit and view results") : (locale === "zh" ? "提交并进入下一时点" : "Commit and reveal next moment")} →</button>}
          </div>
        </section>
      </div>
    </main>
  );
}
