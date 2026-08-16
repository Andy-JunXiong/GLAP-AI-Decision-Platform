"use client";

import { useCallback, useEffect, useState } from "react";
import FormalStoryReview from "./pilot/human-evaluation/FormalStoryReview";
import { copy, t } from "../lib/translations";
import type { Locale, ReviewBootstrap, StoryReviewAnswer } from "../lib/review-types";

type Stage = "loading" | "login" | "welcome" | "review" | "submitted" | "error";

type ProgressPayload = {
  bootstrap: ReviewBootstrap;
  session: null | {
    locale: Locale;
    status: "DRAFT" | "SUBMITTED";
    currentIndex: number;
    submittedAt: string | null;
  };
  answers: StoryReviewAnswer[];
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
  const [answers, setAnswers] = useState<Record<string, StoryReviewAnswer>>({});
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [attestations, setAttestations] = useState({ independent: false, noConflict: false, noBlindKey: false });
  const [message, setMessage] = useState("");
  const [submittedAt, setSubmittedAt] = useState<string | null>(null);
  const text = t(locale);

  const loadProgress = useCallback(async () => {
    setStage("loading");
    setMessage("");
    try {
      const data = await api() as unknown as ProgressPayload;
      setBootstrap(data.bootstrap);
      setAnswers(Object.fromEntries(data.answers.map((answer) => [answer.reviewId, answer])));
      if (!data.session) {
        setStage("welcome");
        return;
      }
      setLocale(data.session.locale === "en" ? "en" : "zh");
      setAttestations({ independent: true, noConflict: true, noBlindKey: true });
      if (data.session.status === "SUBMITTED") {
        setSubmittedAt(data.session.submittedAt);
        setStage("submitted");
      } else {
        setStage("review");
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

  async function commit(answer: StoryReviewAnswer) {
    try {
      await api({ action: "save", answer, locale });
      setAnswers((current) => ({ ...current, [answer.reviewId]: answer }));
      return true;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : text.saveError);
      return false;
    }
  }

  async function submit() {
    try {
      const result = await api({ action: "submit" });
      setSubmittedAt(String(result.submittedAt));
      setStage("submitted");
      window.scrollTo({ top: 0, behavior: "smooth" });
      return true;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : text.saveError);
      return false;
    }
  }

  if (stage === "review" && bootstrap) {
    return <FormalStoryReview bootstrap={bootstrap} locale={locale} answers={answers} onLocale={changeLocale} onLogout={logout} onCommit={commit} onSubmit={submit} />;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="GLAP review home"><span className="brand-mark">G</span><span>GLAP Human Evaluation</span></a>
        <div className="header-actions">
          <span className="formal-review-badge">{locale === "zh" ? "正式评审 · 故事模式 · 可提交" : "Formal review · story mode · submits"}</span>
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
          <div className="login-copy"><p className="eyebrow">{text.loginEyebrow}</p><h1>{text.loginTitle}</h1><p className="lede">{locale === "zh" ? "登录后进入 10 个不同物流故事、30 个逐步解锁的正式决策时点。" : "Sign in to review 10 distinct logistics stories across 30 progressively revealed decision moments."}</p><div className="security-note"><span>●</span><p>{text.loginPrivacy}</p></div></div>
          <form className="login-card" onSubmit={(event) => void login(event)}>
            <p className="step-label">SECURE ACCESS</p>
            <label>{text.username}<input autoComplete="username" inputMode="text" maxLength={80} value={username} placeholder={text.usernamePlaceholder} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>{text.password}<input autoComplete="current-password" maxLength={128} type="password" value={password} placeholder={text.passwordPlaceholder} onChange={(event) => setPassword(event.target.value)} /></label>
            {message && <p className="form-error" role="alert">{message}</p>}
            <button className="primary-button wide" disabled={loginBusy || !username.trim() || !password} type="submit">{loginBusy ? text.loggingIn : text.login}<span>→</span></button>
          </form>
        </section>
      )}

      {stage === "error" && <section className="center-card error-card"><span className="status-symbol">!</span><h1>{text.accessDenied}</h1><p>{message}</p><button className="primary-button" onClick={() => void loadProgress()}>{text.tryAgain}</button></section>}

      {stage === "welcome" && bootstrap && (
        <section className="welcome-grid">
          <div className="welcome-copy"><p className="eyebrow">FORMAL HUMAN EVALUATION · STORY MODE</p><h1>{locale === "zh" ? "10 个不同故事，30 次当时判断" : "10 distinct stories, 30 point-in-time judgments"}</h1><p className="lede">{locale === "zh" ? "你将扮演十种不同的物流运营角色。每个案例只有三个按时间解锁的时点，方案身份始终隐藏。" : "You will take ten different logistics operating roles. Each case has three time-ordered moments and option identity remains blinded."}</p><div className="scope-note"><span>01</span><p>{locale === "zh" ? "只使用当时可见的信息；后续恢复和结果不会提前显示。" : "Use only information visible at the time; later recovery and outcome facts remain hidden."}</p></div><div className="scope-note"><span>02</span><p>{locale === "zh" ? "每个时点保存后立即锁定，全部 30 个时点完成后才能最终提交。" : "Each moment locks when committed; final submission is available only after all 30 are complete."}</p></div></div>
          <div className="attestation-card">
            <p className="step-label">STEP 01 / 03</p><h2>{text.welcomeTitle}</h2>
            {([ ["independent", text.attIndependent], ["noConflict", text.attConflict], ["noBlindKey", text.attBlind] ] as const).map(([key, label]) => <label className="check-row" key={key}><input type="checkbox" checked={attestations[key]} onChange={(event) => setAttestations({ ...attestations, [key]: event.target.checked })} /><span>{label}</span></label>)}
            {message && <p className="form-error">{message}</p>}
            <button className="primary-button wide" disabled={!Object.values(attestations).every(Boolean)} onClick={() => void start()}>{text.start}<span>→</span></button>
            <p className="bundle-stamp">Bundle {bootstrap.bundleId.slice(0, 8)} · 10 stories · 30 moments · blinded</p>
          </div>
        </section>
      )}

      {stage === "submitted" && bootstrap && <section className="submitted-card"><span className="submitted-mark">✓</span><p className="eyebrow">GLAP · REVIEW COMPLETE</p><h1>{text.submittedTitle}</h1><p className="lede">{text.submittedBody}</p><div className="receipt"><div><span>{text.submittedAt}</span><strong>{submittedAt ? formatDate(submittedAt, locale) : "—"}</strong></div><div><span>Bundle</span><strong>{bootstrap.bundleId}</strong></div><div><span>Status</span><strong>{text.immutable}</strong></div></div></section>}
    </main>
  );
}
