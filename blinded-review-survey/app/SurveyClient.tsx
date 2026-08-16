"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  emptyAnswer,
  isComplete,
  visibleOptionsMatch,
  type DimensionId,
  type Locale,
  type Preference,
  type ReviewAnswer,
  type ReviewBootstrap,
  type ReviewPackage,
} from "../lib/review-types";
import {
  anchorZh,
  copy,
  dimensionZh,
  scenarioContext,
  t,
  translatedRecommendation,
} from "../lib/translations";

type Stage = "loading" | "login" | "welcome" | "review" | "summary" | "submitted" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";

type ProgressPayload = {
  bootstrap: ReviewBootstrap;
  session: null | {
    locale: Locale;
    status: "DRAFT" | "SUBMITTED";
    currentIndex: number;
    submittedAt: string | null;
  };
  answers: ReviewAnswer[];
};

class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function formatDate(value: string, locale: Locale) {
  return new Intl.DateTimeFormat(locale === "zh" ? "zh-CN" : "en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Australia/Sydney",
  }).format(new Date(value));
}

function api(payload?: Record<string, unknown>) {
  return fetch("/api/review", payload ? {
    method: "POST",
    headers: { "content-type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  } : { cache: "no-store", credentials: "same-origin" }).then(async (response) => {
    const contentType = response.headers.get("content-type") ?? "";
    const data = contentType.includes("application/json")
      ? await response.json() as Record<string, unknown>
      : { error: await response.text() };
    if (!response.ok) throw new ApiError(String(data.error ?? "Request failed"), response.status);
    return data;
  });
}

export default function SurveyClient() {
  const [bootstrap, setBootstrap] = useState<ReviewBootstrap | null>(null);
  const [locale, setLocale] = useState<Locale>("zh");
  const [stage, setStage] = useState<Stage>("loading");
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, ReviewAnswer>>({});
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [attestations, setAttestations] = useState({ independent: false, noConflict: false, noBlindKey: false });
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [message, setMessage] = useState("");
  const [submittedAt, setSubmittedAt] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);
  const text = t(locale);

  const loadProgress = useCallback(async () => {
    setStage("loading");
    setMessage("");
    try {
      const data = await api() as unknown as ProgressPayload;
      setBootstrap(data.bootstrap);
      const blankAnswers = Object.fromEntries(data.bootstrap.packages.map((item) => [item.review_id, emptyAnswer(item)]));
      setAnswers({ ...blankAnswers, ...Object.fromEntries(data.answers.map((item) => [item.reviewId, item])) });
      if (!data.session) {
        setStage("welcome");
        return;
      }
      setLocale(data.session.locale === "en" ? "en" : "zh");
      setIndex(Math.max(0, Math.min(29, data.session.currentIndex)));
      if (data.session.status === "SUBMITTED") {
        setSubmittedAt(data.session.submittedAt);
        setStage("submitted");
      } else {
        setAttestations({ independent: true, noConflict: true, noBlindKey: true });
        setStage(data.session.currentIndex >= 30 ? "summary" : "review");
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setBootstrap(null);
        setAnswers({});
        setStage("login");
        return;
      }
      setMessage(error instanceof Error ? error.message : "Unable to load");
      setStage("error");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProgress(), 0);
    return () => window.clearTimeout(timer);
  }, [loadProgress]);

  const completedCount = useMemo(
    () => Object.values(answers).filter(isComplete).length,
    [answers],
  );
  const item = bootstrap?.packages[index] ?? null;
  const answer = item ? answers[item.review_id] : null;
  const context = item ? scenarioContext(item, locale) : null;

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username, password }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new ApiError(data.error ?? text.loginError, response.status);
      setPassword("");
      await loadProgress();
    } catch (error) {
      setMessage(error instanceof ApiError && error.status === 429 ? error.message : text.loginError);
    } finally {
      setLoginBusy(false);
    }
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    setBootstrap(null);
    setAnswers({});
    setUsername("");
    setPassword("");
    setMessage("");
    setStage("login");
  }

  function changeLocale(next: Locale) {
    setLocale(next);
    document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
  }

  async function start() {
    setMessage("");
    try {
      await api({ action: "start", locale, attestations });
      setStage("review");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to start");
    }
  }

  function updateAnswer(mutator: (value: ReviewAnswer) => ReviewAnswer) {
    if (!item) return;
    setAnswers((current) => ({ ...current, [item.review_id]: mutator(current[item.review_id]) }));
    setSaveState("idle");
    setMessage("");
  }

  async function save(currentIndex: number) {
    if (!item) return false;
    setSaveState("saving");
    try {
      await api({ action: "save", answer: answers[item.review_id], currentIndex, locale });
      setSaveState("saved");
      return true;
    } catch (error) {
      setSaveState("error");
      setMessage(error instanceof Error ? error.message : text.saveError);
      return false;
    }
  }

  async function goNext() {
    if (!answer || !bootstrap) return;
    if (!isComplete(answer)) {
      setMessage(text.required);
      document.querySelector(".preference-card")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const nextIndex = index + 1;
    if (!await save(nextIndex)) return;
    if (nextIndex >= bootstrap.packages.length) setStage("summary");
    else { setIndex(nextIndex); setShowSource(false); window.scrollTo({ top: 0, behavior: "smooth" }); }
  }

  async function goPrevious() {
    if (!bootstrap || !answer) return;
    await save(Math.max(0, index - 1));
    setIndex(Math.max(0, index - 1));
    setShowSource(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function submit() {
    if (!bootstrap || completedCount !== bootstrap.packages.length) return;
    setSaveState("saving");
    setMessage("");
    try {
      const result = await api({ action: "submit" });
      setSubmittedAt(String(result.submittedAt));
      setSaveState("saved");
      setStage("submitted");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      setSaveState("error");
      setMessage(error instanceof Error ? error.message : text.saveError);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GLAP review home">
          <span className="brand-mark">G</span><span>GLAP Human Evaluation</span>
        </a>
        <div className="header-actions">
          <span className="formal-review-badge">{locale === "zh" ? "正式评审 · 可提交" : "Formal review · submits"}</span>
          {bootstrap && <button className="logout-button" onClick={() => void logout()}>{text.logout}</button>}
          <div className="language-switch" role="group" aria-label={text.language}>
            <button className={locale === "zh" ? "active" : ""} onClick={() => changeLocale("zh")}>{copy.zh.chinese}</button>
            <button className={locale === "en" ? "active" : ""} onClick={() => changeLocale("en")}>{copy.en.english}</button>
          </div>
        </div>
      </header>

      {stage === "loading" && <section className="center-card"><div className="loader" /><p>{text.loading}</p></section>}

      {stage === "login" && (
        <section className="login-grid">
          <div className="login-copy">
            <p className="eyebrow">{text.loginEyebrow}</p>
            <h1>{text.loginTitle}</h1>
            <p className="lede">{text.loginBody}</p>
            <div className="security-note"><span>●</span><p>{text.loginPrivacy}</p></div>
          </div>
          <form className="login-card" onSubmit={(event) => void login(event)}>
            <p className="step-label">SECURE ACCESS</p>
            <label>{text.username}<input autoComplete="username" inputMode="text" maxLength={80} value={username} placeholder={text.usernamePlaceholder} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>{text.password}<input autoComplete="current-password" maxLength={128} type="password" value={password} placeholder={text.passwordPlaceholder} onChange={(event) => setPassword(event.target.value)} /></label>
            {message && <p className="form-error" role="alert">{message}</p>}
            <button className="primary-button wide" disabled={loginBusy || !username.trim() || !password} type="submit">{loginBusy ? text.loggingIn : text.login}<span>→</span></button>
          </form>
        </section>
      )}

      {stage === "error" && (
        <section className="center-card error-card"><span className="status-symbol">!</span><h1>{text.accessDenied}</h1><p>{message}</p><button className="primary-button" onClick={() => void loadProgress()}>{text.tryAgain}</button></section>
      )}

      {stage === "welcome" && bootstrap && (
        <section className="welcome-grid">
          <div className="welcome-copy">
            <p className="eyebrow">{text.eyebrow}</p>
            <h1>{text.title}</h1>
            <p className="lede">{text.subtitle}</p>
            <div className="scope-note"><span>01</span><p>{text.welcomeBody}</p></div>
            <div className="scope-note"><span>02</span><p>{text.sourceNote}</p></div>
          </div>
          <div className="attestation-card">
            <p className="step-label">STEP 01 / 03</p>
            <h2>{text.welcomeTitle}</h2>
            {([
              ["independent", text.attIndependent],
              ["noConflict", text.attConflict],
              ["noBlindKey", text.attBlind],
            ] as const).map(([key, label]) => (
              <label className="check-row" key={key}>
                <input type="checkbox" checked={attestations[key]} onChange={(event) => setAttestations({ ...attestations, [key]: event.target.checked })} />
                <span>{label}</span>
              </label>
            ))}
            {message && <p className="form-error">{message}</p>}
            <button className="primary-button wide" disabled={!Object.values(attestations).every(Boolean)} onClick={() => void start()}>{text.start}<span>→</span></button>
            <p className="bundle-stamp">Bundle {bootstrap.bundleId.slice(0, 8)} · 30 packages · blinded</p>
          </div>
        </section>
      )}

      {stage === "review" && bootstrap && item && answer && (
        <>
          <section className="progress-panel" id="top">
            <div><p className="eyebrow">{text.progress}</p><strong>{completedCount} / {bootstrap.packages.length}</strong><span>{text.completed}</span></div>
            <div className="progress-track"><i style={{ width: `${(completedCount / bootstrap.packages.length) * 100}%` }} /></div>
            <div className={`save-pill ${saveState}`}>{saveState === "saving" ? text.saving : saveState === "error" ? text.saveError : text.saved}</div>
          </section>

          <section className="case-header">
            <div className="case-number"><span>{text.case}</span><strong>{String(index + 1).padStart(2, "0")}</strong><small>{text.of} {bootstrap.packages.length}</small></div>
            <div><p className="cutoff">{text.cutoff} · {formatDate(item.scenario.cutoff_at, locale)}</p><h1>{locale === "zh" ? item.scenario.scenario_title_zh ?? item.scenario.scenario_title : item.scenario.scenario_title}</h1>{locale === "zh" && <p className="source-title">{item.scenario.scenario_title}</p>}</div>
          </section>

          <section className="context-grid">
            <article className="panel context-card"><p className="panel-label">{text.operationalContext}</p><div className="case-label-note"><span aria-hidden="true">i</span><p>{text.caseLabelNote}</p></div><div className="context-narrative">
              <section><h2>{text.contextMoment}</h2><p>{context?.story_summary}</p></section>
              <section><h2>{text.contextKnown}</h2><p>{context?.decision_pressure}</p></section>
              <section><h2>{text.contextExposure}</h2><ul>{context?.difficulty_points.map((point) => <li key={point}>{point}</li>)}</ul></section>
              <section><h2>{text.contextImpact}</h2><ul>{context?.downstream_risks.map((risk) => <li key={risk}>{risk}</li>)}</ul></section>
              <section className="decision-question"><h2>{text.contextQuestion}</h2><p>{context?.decision_question}</p><small><strong>{text.factBoundary}:</strong> {context?.fact_boundary}</small></section>
            </div><dl>
              <div><dt>{locale === "zh" ? "库存覆盖" : "Inventory cover"}</dt><dd>{item.scenario.operational_state.inventory_cover_days} {locale === "zh" ? "天" : "days"}</dd></div>
              <div><dt>{locale === "zh" ? "SLA 关键度" : "SLA criticality"}</dt><dd>{item.scenario.operational_state.sla_criticality}</dd></div>
              <div><dt>{locale === "zh" ? "暴露于中断节点" : "Exposed to disruption"}</dt><dd>{item.scenario.operational_state.exposed_to_disruption_node ? text.yes : text.no}</dd></div>
              <div><dt>{locale === "zh" ? "替代运力" : "Alternate capacity"}</dt><dd>{item.scenario.operational_state.alternate_capacity_available ? text.yes : text.no}</dd></div>
            </dl></article>
            <article className="panel policy-card"><p className="panel-label">{text.policy}</p><p>{text.policyBody}</p><div className="policy-tags"><span>HUMAN GATE</span><span>NO EXECUTION</span><span>NO OUTCOME CLAIM</span></div></article>
          </section>

          <section className="panel evidence-panel">
            <div className="section-heading"><div><p className="panel-label">{text.evidence}</p><h2>{item.scenario.visible_evidence.length} {locale === "zh" ? "个来源" : "sources"}</h2></div>{locale === "zh" && <button className="text-button" onClick={() => setShowSource(!showSource)}>{showSource ? "隐藏英文原文" : "查看英文原文"}</button>}</div>
            <div className="evidence-list">{item.scenario.visible_evidence.map((evidence) => <article key={evidence.evidence_id} className="evidence-item"><div className="evidence-meta"><strong>{evidence.evidence_id}</strong><span>{evidence.evidence_type.replaceAll("_", " ")}</span><time>{formatDate(evidence.available_at, locale)}</time></div>{evidence.facts.map((fact) => <div className="fact" key={fact.fact_id}><span className={`severity ${fact.severity.toLowerCase()}`}>{fact.severity}</span><div><p>{locale === "zh" ? fact.summary_zh ?? fact.summary : fact.summary}</p>{locale === "zh" && showSource && <p className="english-source">{fact.summary}</p>}<small>{fact.signal_type.replaceAll("_", " ")}</small></div></div>)}</article>)}</div>
          </section>

          <section className="options-section">
            <div className="options-intro"><p className="eyebrow">STEP 02 / 03</p><h2>{text.optionsTitle}</h2><p>{text.optionsHint}</p></div>
            {visibleOptionsMatch(item) && <aside className="identical-options-note" role="note" aria-label={text.identicalOptionsTitle}><span aria-hidden="true">≡</span><div><p>{text.identicalOptionsEyebrow}</p><strong>{text.identicalOptionsTitle}</strong><p>{text.identicalOptionsBody}</p></div></aside>}
            <div className="option-grid">{item.options.map((option, optionIndex) => {
              const scoreKey = optionIndex === 0 ? "optionA" : "optionB";
              const scores = answer[scoreKey];
              return <article className="option-card" key={option.option_id}>
                <div className="option-head"><span>{optionIndex === 0 ? "A" : "B"}</span><div><p>{optionIndex === 0 ? text.optionA : text.optionB}</p><h3>{translatedRecommendation(option.recommendation, locale)}</h3></div></div>
                <dl className="option-summary"><div><dt>{text.priority}</dt><dd>{option.priority}</dd></div><div><dt>{text.humanReview}</dt><dd>{option.human_review_required ? text.yes : text.no}</dd></div></dl>
                <DecisionDetails locale={locale} option={option} />
                <div className="score-list">{bootstrap.dimensions.map((dimension) => <ScoreRow key={dimension.id} locale={locale} dimension={dimension} value={scores[dimension.id]} onChange={(score) => updateAnswer((current) => ({ ...current, [scoreKey]: { ...current[scoreKey], [dimension.id]: score } }))} />)}</div>
              </article>;
            })}</div>
          </section>

          <section className="panel preference-card">
            <div><p className="panel-label">STEP 03 / 03</p><h2>{text.preference}</h2></div>
            <div className="choice-row">{(["OPTION_A", "OPTION_B", "TIE"] as Preference[]).map((choice) => <button key={choice} className={answer.preferred === choice ? "selected" : ""} onClick={() => updateAnswer((current) => ({ ...current, preferred: choice }))}>{choice === "OPTION_A" ? text.optionA : choice === "OPTION_B" ? text.optionB : text.tie}</button>)}</div>
            <div className="confidence-block"><label>{text.confidence}</label><div className="confidence-row">{[1,2,3,4,5].map((value) => <button key={value} className={answer.confidence === value ? "selected" : ""} onClick={() => updateAnswer((current) => ({ ...current, confidence: value }))}>{value}</button>)}</div><div className="range-labels"><span>{text.confidenceLow}</span><span>{text.confidenceHigh}</span></div></div>
            <label className="notes-label">{text.notes}<textarea maxLength={1000} value={answer.notes} placeholder={text.notesPlaceholder} onChange={(event) => updateAnswer((current) => ({ ...current, notes: event.target.value }))} /><small>{answer.notes.length} / 1000</small></label>
            {message && <p className="form-error">{message}</p>}
          </section>

          <nav className="bottom-actions"><button className="secondary-button" disabled={index === 0 || saveState === "saving"} onClick={() => void goPrevious()}>← {text.previous}</button><button className="primary-button" disabled={saveState === "saving"} onClick={() => void goNext()}>{index === 29 ? text.review : text.next}<span>→</span></button></nav>
        </>
      )}

      {stage === "summary" && bootstrap && (
        <section className="summary-page"><p className="eyebrow">STEP 03 / 03</p><h1>{text.finalTitle}</h1><p className="lede">{text.finalBody}</p><div className={`completion-banner ${completedCount === 30 ? "ready" : "not-ready"}`}><span>{completedCount === 30 ? "✓" : "!"}</span><div><strong>{completedCount === 30 ? text.allComplete : text.incomplete}</strong><p>{completedCount} / 30</p></div></div><div className="case-index">{bootstrap.packages.map((pkg, i) => <button key={pkg.review_id} className={isComplete(answers[pkg.review_id]) ? "done" : ""} onClick={() => { setIndex(i); setStage("review"); }}>{i + 1}</button>)}</div>{message && <p className="form-error">{message}</p>}<div className="summary-actions"><button className="secondary-button" onClick={() => { setIndex(29); setStage("review"); }}>← {text.previous}</button><button className="primary-button" disabled={completedCount !== 30 || saveState === "saving"} onClick={() => void submit()}>{saveState === "saving" ? text.submitting : text.submit}<span>→</span></button></div></section>
      )}

      {stage === "submitted" && bootstrap && (
        <section className="submitted-card"><span className="submitted-mark">✓</span><p className="eyebrow">GLAP · REVIEW COMPLETE</p><h1>{text.submittedTitle}</h1><p className="lede">{text.submittedBody}</p><div className="receipt"><div><span>{text.submittedAt}</span><strong>{submittedAt ? formatDate(submittedAt, locale) : "—"}</strong></div><div><span>Bundle</span><strong>{bootstrap.bundleId}</strong></div><div><span>Status</span><strong>{text.immutable}</strong></div></div></section>
      )}
    </main>
  );
}

const codeZh: Record<string, string> = {
  CURRENT_GOVERNED_REVIEW: "当前受治理复核",
  NEXT_GOVERNED_REVIEW: "下一个受治理复核点",
  BEFORE_HUMAN_APPROVAL: "人工批准前",
  BEFORE_ANY_OPERATIONAL_CHANGE: "任何运营变更前",
  ONLY_IF_TRIGGERED: "仅在触发时",
  ANALYST_PREPARES_HUMAN_REVIEWS: "分析人员准备，人工复核",
  ANALYST_MONITORS_HUMAN_REVIEWS: "分析人员监测，人工复核",
  NAMED_HUMAN_APPROVAL_REQUIRED: "必须由具名人员批准",
  ANALYZE_CUTOFF_EVIDENCE: "分析截止时间前可用证据",
  PREPARE_BOUNDED_PROPOSAL: "准备范围受限的建议",
  REQUEST_HUMAN_REVIEW: "请求人工复核",
  BOOK_CAPACITY: "预订运力",
  REROUTE_SHIPMENT: "货运改道",
  COMMIT_SPEND: "承诺支出",
  CLAIM_BUSINESS_OUTCOME: "声称业务结果",
};

function displayCode(value: string, locale: Locale) {
  return locale === "zh" ? codeZh[value] ?? value : value.replaceAll("_", " ").toLowerCase();
}

function DecisionDetails({ locale, option }: {
  locale: Locale;
  option: ReviewPackage["options"][number];
}) {
  const text = t(locale);
  const content = option.content;
  const localized = locale === "zh" ? option.content_zh : undefined;
  const basis = localized?.decision_basis ?? content.decision_basis;
  const problem = localized?.problem_response ?? content.problem_response;
  const risk = localized?.risk_assessment ?? content.risk_assessment;
  const plan = localized?.action_plan ?? content.action_plan;
  const solutions = localized?.solution_horizons ?? content.solution_horizons;
  const benefits = localized?.intended_benefits ?? content.intended_benefits;
  const tradeoffs = localized?.tradeoffs_and_uncertainty ?? content.tradeoffs_and_uncertainty;

  return <div className="decision-details">
    <section className="decision-block basis-block">
      <p className="decision-label">{text.decisionBasis}</p>
      <p className="decision-lead">{basis.summary}</p>
      <div className="severity-line"><span>{text.strongestSeverity}</span><strong>{content.decision_basis.strongest_visible_severity}</strong></div>
      <h4>{text.evidenceCitations}</h4>
      {basis.evidence_citations.length === 0
        ? <p className="empty-citation">{text.noEvidenceCitations}</p>
        : <ul className="citation-list">{basis.evidence_citations.map((citation) => <li key={citation.evidence_id}>
            <strong>{citation.evidence_id}</strong>
            <span>{citation.fact_ids.join(" · ")}</span>
            <p>{citation.why_relevant}</p>
          </li>)}</ul>}
    </section>

    <section className="decision-block problem-block">
      <p className="decision-label">{text.primaryProblem}</p>
      <p className="decision-lead">{problem.primary_problem}</p>
      <div className="problem-columns"><div><h4>{text.difficultyPoints}</h4><ul>{problem.difficulty_points.map((point) => <li key={point}>{point}</li>)}</ul></div><div><h4>{text.impactPathways}</h4><ul>{problem.impact_pathways.map((impact) => <li key={impact}>{impact}</li>)}</ul></div></div>
    </section>

    <section className="decision-block">
      <p className="decision-label">{text.riskAssessment}</p>
      <div className="risk-level"><span>{text.riskLevel}</span><strong>{content.risk_assessment.risk_level}</strong></div>
      <p>{risk.risk_statement}</p>
      <p className="supporting-copy">{risk.exposure_statement}</p>
    </section>

    <section className="decision-block solution-block">
      <p className="decision-label">{text.solutionHorizons}</p>
      <div className="solution-timeline">{(["immediate", "short_term", "long_term"] as const).map((key) => {
        const phase = solutions[key];
        const label = key === "immediate" ? text.immediateSolution : key === "short_term" ? text.shortTermSolution : text.longTermSolution;
        return <article key={key}><span>{label}</span><h4>{phase.objective}</h4><ol>{phase.steps.map((step) => <li key={step}>{step}</li>)}</ol></article>;
      })}</div>
      <div className="review-trigger"><strong>{text.reviewTrigger}</strong><p>{plan.review_trigger}</p></div>
    </section>

    <section className="decision-block benefits-block">
      <p className="decision-label">{text.intendedBenefits}</p>
      <div className="benefit-columns">{(["short_term", "long_term"] as const).map((key) => <div key={key}><h4>{key === "short_term" ? text.shortTermBenefits : text.longTermBenefits}</h4>{benefits[key].map((item) => <article key={item.benefit}><strong>{item.benefit}</strong><p><span>{text.measurementSignal}</span>{item.measurement_signal}</p><small>{text.expectedNotObserved}</small></article>)}</div>)}</div>
    </section>

    <section className="decision-block">
      <p className="decision-label">{text.tradeoffs}</p>
      <ul className="tradeoff-list">{tradeoffs.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </section>

    <section className="decision-block authority-block">
      <p className="decision-label">{text.authorityBoundary}</p>
      <strong className="proposal-only">✓ {text.proposalOnly}</strong>
      <div className="authority-list permitted"><span>{text.permittedActions}</span>{content.authority_boundary.permitted_actions.map((item) => <em key={item}>{displayCode(item, locale)}</em>)}</div>
      <div className="authority-list prohibited"><span>{text.prohibitedActions}</span>{content.authority_boundary.prohibited_actions.map((item) => <em key={item}>{displayCode(item, locale)}</em>)}</div>
    </section>

    {locale === "zh" && <details className="frozen-source-details">
      <summary>查看本方案的英文冻结原文</summary>
      <p><strong>Decision basis:</strong> {content.decision_basis.summary}</p>
      <p><strong>Risk:</strong> {content.risk_assessment.risk_statement}</p>
      <p><strong>Problem:</strong> {content.problem_response.primary_problem}</p>
      {(["immediate", "short_term", "long_term"] as const).map((key) => <div key={key}><p><strong>{key.replaceAll("_", " ")} solution:</strong> {content.solution_horizons[key].objective}</p><ol>{content.solution_horizons[key].steps.map((step) => <li key={step}>{step}</li>)}</ol></div>)}
      <p><strong>Review trigger:</strong> {content.action_plan.review_trigger}</p>
      <ul>{content.tradeoffs_and_uncertainty.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </details>}
  </div>;
}

function ScoreRow({ locale, dimension, value, onChange }: {
  locale: Locale;
  dimension: ReviewBootstrap["dimensions"][number];
  value: number | null;
  onChange: (score: number) => void;
}) {
  const title = locale === "zh" ? dimensionZh[dimension.id as DimensionId].title : dimension.id.replaceAll("_", " ");
  const question = locale === "zh" ? dimensionZh[dimension.id as DimensionId].question : dimension.question;
  const anchor = value === null ? null : locale === "zh" ? anchorZh[dimension.id as DimensionId][value] : dimension.anchors[String(value)];
  return <div className="score-row"><div className="score-copy"><strong>{title}<i>{Math.round(dimension.weight * 100)}%</i></strong><p>{question}</p></div><div className="score-buttons" role="group" aria-label={`${title} ${t(locale).score}`}>{[0,1,2,3,4].map((score) => <button key={score} className={value === score ? "selected" : ""} onClick={() => onChange(score)} aria-pressed={value === score}>{score}</button>)}</div>{anchor && <p className="anchor-text"><span>{t(locale).anchor}</span>{anchor}</p>}</div>;
}
