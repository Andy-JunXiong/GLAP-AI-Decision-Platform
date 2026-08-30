"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  ActionEvidence,
  ActionOperation,
  DecisionBriefV1,
  OperationsAction,
  OperationsOutcome,
  OutcomeCohortSummary,
  PipelineHealth as PipelineHealthData,
  ForecastContract,
  LearningEvidence,
  ProviderLabelReadiness,
  NetworkResponse,
  NetworkSummary,
  OperationsRisk,
  ShipmentEntity,
  internalOperationsEnabled,
  loadActionQueue,
  loadActionEvidence,
  loadOutcomeReview,
  loadPipelineHealth,
  loadForecastAccuracy,
  loadLearningEvidence,
  loadLabelReadiness,
  loadNetworkSummary,
  loadRiskHotspots,
  loadShipmentDrilldown,
  mutateAction,
  readOperationsToken,
} from "./operations-api";
import {
  OutcomeComparisonFingerprintReason,
  OutcomeComparisonFingerprintVerification,
  isOutcomeComparisonFingerprintRetryable,
  verifyOutcomeComparisonFingerprint,
} from "./outcome-comparison-fingerprint";
import {
  finishOperationsSignIn,
  internalAuthenticationEnabled,
  operationsSignedIn,
  signInOperations,
  signOutOperations,
} from "./operations-auth";
import {
  decisionReviewHandoffMessage,
  resolveDecisionReviewHandoff,
} from "./decision-review-handoff";
import {
  decisionSeverityCount,
  decisionSeverityFilters,
  filterDecisionQueue,
  type DecisionSeverityFilter,
  waitingDecisionActions,
} from "./decision-queue-filter";
import {
  loadSystemEvidenceSnapshot,
  type SystemEvidenceSnapshot,
} from "./system-evidence-snapshot";
import "./operations.css";

type View = "overview" | "signals" | "decisions" | "actions" | "shipments" | "outcomes" | "learning" | "readiness" | "system" | "forecasts" | "health" | "brief";
type OperationsLoadState = "demo" | "loading" | "connected" | "auth_required" | "error";
type ShipmentLoadState = "idle" | "loading" | "connected" | "partial" | "error";
type DataStateKind = "loading" | "empty" | "stale" | "partial" | "failed" | "auth_required" | "idle";

const comparisonFingerprintDiagnostic: Record<
  Exclude<OutcomeComparisonFingerprintReason, "MATCH">,
  string
> = {
  MISSING_INTEGRITY: "The response does not include the required v1 integrity contract.",
  CONTRACT_METADATA_MISMATCH: "The integrity metadata or bounded trust flags do not match the v1 contract.",
  CRYPTO_UNAVAILABLE: "Browser cryptography is unavailable for this verification attempt.",
  NON_CANONICAL_CONTENT: "The covered response values do not satisfy the canonical comparison format.",
  DIGEST_MISMATCH: "The recomputed digest does not match the response fingerprint.",
  VERIFICATION_ERROR: "Browser verification could not complete safely.",
};

const navItems: { id: View; label: string; icon: string; internalOnly?: boolean }[] = [
  { id: "overview", label: "Control Tower", icon: "⌂" },
  { id: "signals", label: "Signals", icon: "⌁" },
  { id: "decisions", label: "Decisions", icon: "◇" },
  { id: "shipments", label: "Shipments", icon: "▣" },
  { id: "outcomes", label: "Outcomes", icon: "↗" },
  { id: "actions", label: "Action Board", icon: "A" },
  { id: "learning", label: "Learning Review", icon: "L", internalOnly: true },
  { id: "readiness", label: "Label Readiness", icon: "R", internalOnly: true },
  { id: "system", label: "System", icon: "S" },
  { id: "health", label: "Pipeline Health", icon: "H" },
  { id: "forecasts", label: "Forecast Accuracy", icon: "F" },
];

const signals = [
  { severity: "Critical", title: "Sydney port disruption", source: "Port congestion + labour", value: "0.87 risk index", affected: "12 FCL", time: "12 min ago" },
  { severity: "High", title: "Singapore transshipment delay", source: "Schedule reliability", value: "+3.2 days", affected: "8 shipments", time: "38 min ago" },
  { severity: "High", title: "Brisbane inventory pressure", source: "Inventory planning", value: "6 days cover", affected: "3 critical SKUs", time: "1 hr ago" },
  { severity: "Medium", title: "Shanghai rate movement", source: "Freight market", value: "+14% WoW", affected: "2 trade lanes", time: "3 hrs ago" },
];

const decisions = [
  { priority: "Critical", title: "Divert 8 FCL via Melbourne", id: "DEC-PORT-0001", owner: "Mia Chen", value: "AUD 5,760", status: "Review now", due: "2h 14m" },
  { priority: "High", title: "Expedite critical SKU replenishment", id: "DEC-INV-0007", owner: "James Wu", value: "AUD 18,400", status: "Pending", due: "6h 30m" },
  { priority: "Medium", title: "Hold Shanghai spot-rate booking", id: "DEC-RATE-0012", owner: "Sarah Lim", value: "AUD 3,200", status: "Monitoring", due: "1d 4h" },
];

const shipments = [
  { ref: "GLAP-48291", route: "Shanghai → Sydney", eta: "29 Jul", fcl: 8, inventory: "8 days", risk: "Critical", action: "Divert" },
  { ref: "GLAP-48304", route: "Ningbo → Sydney", eta: "30 Jul", fcl: 4, inventory: "15 days", risk: "High", action: "Monitor" },
  { ref: "GLAP-48177", route: "Singapore → Melbourne", eta: "28 Jul", fcl: 6, inventory: "21 days", risk: "Medium", action: "No change" },
  { ref: "GLAP-48093", route: "Busan → Brisbane", eta: "27 Jul", fcl: 3, inventory: "6 days", risk: "High", action: "Expedite" },
];

const money = (value: number) => new Intl.NumberFormat("en-AU", {
  style: "currency", currency: "AUD", maximumFractionDigits: 0,
}).format(value);

export default function Home() {
  const [view, setView] = useState<View>("overview");
  const [diverted, setDiverted] = useState(8);
  const [decision, setDecision] = useState<"pending" | "approved" | "rejected">("pending");
  const [signalFilter, setSignalFilter] = useState("All");
  const [selectedDecisionBrief, setSelectedDecisionBrief] = useState<DecisionBriefV1 | null>(null);
  const [selectedReviewActionId, setSelectedReviewActionId] = useState<string | null>(null);
  const [reviewHandoffMessage, setReviewHandoffMessage] = useState("");
  const [operationsActions, setOperationsActions] = useState<OperationsAction[]>([]);
  const [operationsRisks, setOperationsRisks] = useState<OperationsRisk[]>([]);
  const [operationsOutcomes, setOperationsOutcomes] = useState<OperationsOutcome[]>([]);
  const [outcomeCohortSummary, setOutcomeCohortSummary] = useState<OutcomeCohortSummary | null>(null);
  const [pipelineHealth, setPipelineHealth] = useState<PipelineHealthData | null>(null);
  const [forecastContract, setForecastContract] = useState<ForecastContract | null>(null);
  const [learningContract, setLearningContract] = useState<LearningEvidence | null>(null);
  const [labelReadinessContract, setLabelReadinessContract] = useState<ProviderLabelReadiness | null>(null);
  const [networkContract, setNetworkContract] = useState<NetworkResponse | null>(null);
  const [shipmentEntities, setShipmentEntities] = useState<ShipmentEntity[]>([]);
  const [shipmentNextToken, setShipmentNextToken] = useState<string | null>(null);
  const [shipmentSelection, setShipmentSelection] = useState<NetworkSummary | null>(null);
  const [operationsState, setOperationsState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [operationsMessage, setOperationsMessage] = useState("");
  const [healthState, setHealthState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [healthMessage, setHealthMessage] = useState("");
  const [forecastState, setForecastState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [forecastMessage, setForecastMessage] = useState("");
  const [learningState, setLearningState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [learningMessage, setLearningMessage] = useState("");
  const [labelReadinessState, setLabelReadinessState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [labelReadinessMessage, setLabelReadinessMessage] = useState("");
  const [networkState, setNetworkState] = useState<OperationsLoadState>(
    internalOperationsEnabled() ? "loading" : "demo",
  );
  const [networkMessage, setNetworkMessage] = useState("");
  const [shipmentState, setShipmentState] = useState<ShipmentLoadState>("idle");
  const [signedIn, setSignedIn] = useState(false);

  const refreshOperations = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setOperationsState("auth_required");
      setOperationsMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setOperationsState("loading");
    try {
      const [queue, risks, outcomes] = await Promise.all([
        loadActionQueue(token),
        loadRiskHotspots(token, "OPEN"),
        loadOutcomeReview(token),
      ]);
      setOperationsActions(queue.items);
      setOperationsRisks(risks.items);
      setOperationsOutcomes(outcomes.items);
      setOutcomeCohortSummary(outcomes.cohort_summary ?? null);
      setOperationsState("connected");
      setOperationsMessage("");
    } catch (error) {
      setOperationsState("error");
      setOperationsMessage(error instanceof Error ? error.message : "Unable to load Operations API");
    }
  }, []);

  const refreshPipelineHealth = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setHealthState("auth_required");
      setHealthMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setHealthState("loading");
    try {
      setPipelineHealth(await loadPipelineHealth(token));
      setHealthState("connected");
      setHealthMessage("");
    } catch (error) {
      setHealthState("error");
      setHealthMessage(error instanceof Error ? error.message : "Unable to load Pipeline Health");
    }
  }, []);

  const refreshForecasts = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setForecastState("auth_required");
      setForecastMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setForecastState("loading");
    try {
      setForecastContract(await loadForecastAccuracy(token));
      setForecastState("connected");
      setForecastMessage("");
    } catch (error) {
      setForecastState("error");
      setForecastMessage(error instanceof Error ? error.message : "Unable to load Forecast Accuracy");
    }
  }, []);

  const refreshLearning = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setLearningState("auth_required");
      setLearningMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setLearningState("loading");
    try {
      setLearningContract(await loadLearningEvidence(token));
      setLearningState("connected");
      setLearningMessage("");
    } catch (error) {
      setLearningState("error");
      setLearningMessage(error instanceof Error ? error.message : "Unable to load Learning evidence");
    }
  }, []);

  const refreshLabelReadiness = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setLabelReadinessState("auth_required");
      setLabelReadinessMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setLabelReadinessState("loading");
    try {
      setLabelReadinessContract(await loadLabelReadiness(token));
      setLabelReadinessState("connected");
      setLabelReadinessMessage("");
    } catch (error) {
      setLabelReadinessState("error");
      setLabelReadinessMessage(error instanceof Error ? error.message : "Unable to load label readiness");
    }
  }, []);

  const refreshNetwork = useCallback(async () => {
    if (!internalOperationsEnabled()) return;
    const token = readOperationsToken();
    if (!token) {
      setNetworkState("auth_required");
      setNetworkMessage("Sign in through the approved internal identity provider.");
      return;
    }
    setNetworkState("loading");
    try {
      setNetworkContract(await loadNetworkSummary(token));
      setShipmentEntities([]);
      setShipmentSelection(null);
      setShipmentNextToken(null);
      setShipmentState("idle");
      setNetworkState("connected");
      setNetworkMessage("");
    } catch (error) {
      setNetworkState("error");
      setNetworkMessage(error instanceof Error ? error.message : "Unable to load Network Drill-down");
    }
  }, []);

  const openShipmentGroup = useCallback(async (selection: NetworkSummary) => {
    setShipmentSelection(selection);
    setShipmentEntities([]);
    setShipmentNextToken(null);
    setShipmentState("loading");
    try {
      const response = await loadShipmentDrilldown(readOperationsToken(), {
        mode: selection.transport_mode,
        provider: selection.provider_code,
        lane: selection.market_lane,
      });
      setShipmentEntities(response.items);
      setShipmentNextToken(response.next_token);
      setShipmentState("connected");
    } catch (error) {
      setShipmentState("error");
      setNetworkMessage(error instanceof Error ? error.message : "Unable to load shipment entities");
    }
  }, []);

  const loadMoreShipments = useCallback(async () => {
    if (!shipmentSelection || !shipmentNextToken) return;
    setShipmentState("loading");
    try {
      const response = await loadShipmentDrilldown(readOperationsToken(), {
        mode: shipmentSelection.transport_mode,
        provider: shipmentSelection.provider_code,
        lane: shipmentSelection.market_lane,
        nextToken: shipmentNextToken,
      });
      setShipmentEntities((current) => [...current, ...response.items]);
      setShipmentNextToken(response.next_token);
      setShipmentState("connected");
    } catch (error) {
      setShipmentState(shipmentEntities.length ? "partial" : "error");
      setNetworkMessage(error instanceof Error ? error.message : "Unable to load the next shipment page");
    }
  }, [shipmentEntities.length, shipmentNextToken, shipmentSelection]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => {
      void finishOperationsSignIn()
        .then(() => {
          setSignedIn(operationsSignedIn());
          return Promise.all([refreshOperations(), refreshPipelineHealth(), refreshForecasts(), refreshLearning(), refreshLabelReadiness(), refreshNetwork()]);
        })
        .catch((error) => {
          const signInMessage = error instanceof Error ? error.message : "Internal sign-in failed";
          setOperationsState("error");
          setOperationsMessage(signInMessage);
          setHealthState("error");
          setHealthMessage(signInMessage);
          setForecastState("error");
          setForecastMessage(signInMessage);
          setLearningState("error");
          setLearningMessage(signInMessage);
          setLabelReadinessState("error");
          setLabelReadinessMessage(signInMessage);
          setNetworkState("error");
          setNetworkMessage(signInMessage);
        });
    }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [refreshOperations, refreshPipelineHealth, refreshForecasts, refreshLearning, refreshLabelReadiness, refreshNetwork]);

  const submitOperation = useCallback(async (
    actionId: string, operation: ActionOperation, reason: string,
    assignment: { actionOwner?: string; actionDueDate?: string } = {},
  ) => {
    try {
      await mutateAction(readOperationsToken(), actionId, operation, reason, assignment);
      await refreshOperations();
      return true;
    } catch (error) {
      setOperationsState("error");
      setOperationsMessage(error instanceof Error ? error.message : "Action update failed");
      return false;
    }
  }, [refreshOperations]);

  const economics = useMemo(() => {
    const noAction = 12 * 6 * 220;
    const avoided = diverted * 6 * 220;
    const reroute = diverted * 600;
    return {
      noAction, avoided, reroute, net: avoided - reroute,
      stockout: diverted >= 8 ? "Low" : diverted >= 5 ? "Medium" : "High",
    };
  }, [diverted]);

  const go = (next: View) => {
    if (next !== "brief" && next !== "actions") {
      setSelectedReviewActionId(null);
    }
    setView(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const openDecisionBrief = (brief: DecisionBriefV1) => {
    setSelectedReviewActionId(null);
    setReviewHandoffMessage("");
    setSelectedDecisionBrief(brief);
    go("brief");
  };

  const reviewAction = (action: OperationsAction) => {
    const handoff = resolveDecisionReviewHandoff(action, operationsRisks);
    if (handoff.status === "BLOCKED") {
      setSelectedReviewActionId(null);
      setSelectedDecisionBrief(null);
      setReviewHandoffMessage(decisionReviewHandoffMessage(handoff.reason_code));
      return;
    }
    setSelectedReviewActionId(action.action_id);
    setSelectedDecisionBrief(handoff.brief);
    setReviewHandoffMessage("");
    go("brief");
  };

  const openSelectedAction = () => {
    if (!selectedReviewActionId) return;
    setView("actions");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const navigationLabel = (item: (typeof navItems)[number]) => (
    internalOperationsEnabled() && item.id === "signals"
      ? "Risk Hotspots"
      : item.label
  );
  const currentNavigationItem = navItems.find((item) => item.id === view);
  const currentNavigationLabel = view === "brief"
    ? "Decision Brief"
    : currentNavigationItem
      ? navigationLabel(currentNavigationItem)
      : undefined;
  const waitingDecisionCount = waitingDecisionActions(operationsActions).length;

  return (
    <div className="product-shell">
      <aside className="sidebar">
        <button className="logo" onClick={() => go("overview")} aria-label="GLAP home">
          <span>G</span><div><strong>GLAP</strong><small>Decision Intelligence</small></div>
        </button>
        <nav aria-label="Product navigation">
          <p>Workspace</p>
          {navItems.filter((item) => !item.internalOnly || internalOperationsEnabled()).map((item) => (
            <button aria-label={navigationLabel(item)} key={item.id} className={view === item.id ? "active" : ""} onClick={() => go(item.id)}>
              <i aria-hidden="true">{item.icon}</i>{navigationLabel(item)}
              {item.id === "decisions" && <b>{internalOperationsEnabled() ? waitingDecisionCount : 3}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="system-state"><i /><div><strong>{internalOperationsEnabled() ? "Authenticated monitoring" : "Illustrative mode"}</strong><span>{internalOperationsEnabled() ? "Private staging evidence" : "No live system status"}</span></div></div>
          <div className="user-card"><span>MC</span><div><strong>Mia Chen</strong><small>Import Operations</small></div><i>···</i></div>
        </div>
      </aside>

      <main className="app-main">
        <header className="app-header">
          <div className="mobile-brand"><strong>GLAP</strong></div>
          <div className="header-context">
            <span>Australia Operations</span><b>/</b><strong>{currentNavigationLabel}</strong>
          </div>
          <div className="header-actions">
            <span className="demo-badge">{internalOperationsEnabled() ? "Internal staging" : "Synthetic workspace"}</span>
            {internalOperationsEnabled() && internalAuthenticationEnabled() && (
              signedIn
                ? <button className="auth-button" onClick={signOutOperations}>Sign out</button>
                : <button className="auth-button" onClick={() => { void signInOperations(); }}>Internal sign in</button>
            )}
            <span aria-label="Illustrative notifications" className="notification" role="img">●<b>3</b></span>
            <span aria-label="Help is unavailable in the public walkthrough" className="help" role="img">?</span>
          </div>
        </header>

        {view === "overview" && <Overview go={go} />}
        {view === "signals" && <Signals filter={signalFilter} setFilter={setSignalFilter} go={go} openBrief={openDecisionBrief} risks={operationsRisks} operationsState={operationsState} operationsMessage={operationsMessage} refresh={refreshOperations} />}
        {view === "decisions" && <Decisions go={go} actions={operationsActions} operationsState={operationsState} operationsMessage={operationsMessage} reviewHandoffMessage={reviewHandoffMessage} reviewAction={reviewAction} refresh={refreshOperations} />}
        {view === "actions" && <ActionBoard actions={operationsActions} focusedActionId={selectedReviewActionId} clearFocusedAction={() => setSelectedReviewActionId(null)} backToDecisionBrief={() => go("brief")} openDecisionQueue={() => go("decisions")} operationsState={operationsState} operationsMessage={operationsMessage} submitOperation={submitOperation} refresh={refreshOperations} />}
        {view === "shipments" && <Shipments
          go={go} contract={networkContract} entities={shipmentEntities}
          state={networkState} message={networkMessage} shipmentState={shipmentState}
          selection={shipmentSelection} nextToken={shipmentNextToken}
          refresh={refreshNetwork} openGroup={openShipmentGroup} loadMore={loadMoreShipments}
        />}
        {view === "outcomes" && <Outcomes outcomes={operationsOutcomes} cohortSummary={outcomeCohortSummary} operationsState={operationsState} operationsMessage={operationsMessage} refresh={refreshOperations} />}
        {view === "learning" && <LearningReview contract={learningContract} state={learningState} message={learningMessage} refresh={refreshLearning} />}
        {view === "readiness" && <LabelReadiness contract={labelReadinessContract} state={labelReadinessState} message={labelReadinessMessage} refresh={refreshLabelReadiness} />}
        {view === "system" && <SystemOverview go={go} />}
        {view === "health" && <PipelineHealth health={pipelineHealth} state={healthState} message={healthMessage} refresh={refreshPipelineHealth} />}
        {view === "forecasts" && <ForecastAccuracy contract={forecastContract} state={forecastState} message={forecastMessage} refresh={refreshForecasts} />}
        {view === "brief" && (
          <DecisionBrief
            diverted={diverted}
            setDiverted={setDiverted}
            decision={decision}
            setDecision={setDecision}
            economics={economics}
            contract={selectedDecisionBrief}
            selectedReviewActionId={selectedReviewActionId}
            openSelectedAction={openSelectedAction}
            go={go}
          />
        )}
      </main>
    </div>
  );
}

function PageTitle({ eyebrow, title, copy, action }: { eyebrow: string; title: string; copy: string; action?: React.ReactNode }) {
  return <div className="page-title"><div><span>{eyebrow}</span><h1>{title}</h1><p>{copy}</p></div>{action}</div>;
}

function SystemOverview({ go }: { go: (view: View) => void }) {
  type SystemSection = "flow" | "aws" | "data" | "logic" | "ops" | "release";
  const [section, setSection] = useState<SystemSection>("flow");
  const [evidence, setEvidence] = useState<SystemEvidenceSnapshot | null>(null);
  const [evidenceState, setEvidenceState] = useState<"loading" | "connected" | "failed">("loading");
  const sections: { id: SystemSection; label: string }[] = [
    { id: "flow", label: "Daily E2E Flow" },
    { id: "aws", label: "AWS Overview" },
    { id: "data", label: "Data Catalog" },
    { id: "logic", label: "Logic & SQL" },
    { id: "ops", label: "OPS Dashboard" },
    { id: "release", label: "Release & Lineage" },
  ];

  useEffect(() => {
    let active = true;
    loadSystemEvidenceSnapshot()
      .then((snapshot) => {
        if (!active) return;
        setEvidence(snapshot);
        setEvidenceState("connected");
      })
      .catch(() => {
        if (!active) return;
        setEvidence(null);
        setEvidenceState("failed");
      });
    return () => { active = false; };
  }, []);

  const runtimeEvidence = evidence?.evidence_class === "AWS_RUNTIME_INSPECTION";

  return <div className="page">
    <PageTitle eyebrow="SYSTEM" title="AWS System & Evidence" copy="Understand what is deployed, how the governed decision loop operates, and where public, staging, and production authority remain separated." />
    <section className="demo-boundary" role="status">
      <div><small>{runtimeEvidence ? "Aggregate runtime observation" : "Repository-backed architecture"}</small><strong>Read-only AWS system evidence</strong><span>{runtimeEvidence ? "A separately collected control-plane observation passed the v2 aggregate-only contract. This page still makes no AWS call and exposes no account IDs, ARNs, buckets, query IDs, subscriber details, or mutation controls." : "The architecture and controls below come from the current repository sources of truth. This page performs no AWS inspection and exposes no account IDs, ARNs, buckets, query IDs, subscriber details, or mutation controls."}</span></div>
      <b>{runtimeEvidence ? "SAFE PROJECTION" : "NO LIVE CALLS"}</b>
    </section>
    <nav className="system-section-nav" aria-label="System subpages">
      {sections.map((item) => <button key={item.id} aria-pressed={section === item.id} className={section === item.id ? "active" : ""} onClick={() => setSection(item.id)}>{item.label}</button>)}
    </nav>

    <SystemEvidenceStatus evidence={evidence} state={evidenceState} />

    {section === "flow" && <SystemDailyFlow />}
    {section === "aws" && <SystemAwsOverview evidence={evidence} state={evidenceState} />}
    {section === "data" && <SystemDataCatalog />}
    {section === "logic" && <SystemLogic />}
    {section === "ops" && <SystemOps go={go} evidence={evidence} state={evidenceState} />}
    {section === "release" && <SystemRelease />}

    <p className="data-disclaimer">Validated System evidence is not an AWS console and does not establish production readiness. Logistics records and Outcomes are synthetic; production aliases, schedules, infrastructure changes, Action mutations, policy activation, and model promotion remain separately human-owned.</p>
  </div>;
}

function SystemEvidenceStatus({ evidence, state }: {
  evidence: SystemEvidenceSnapshot | null;
  state: "loading" | "connected" | "failed";
}) {
  if (state === "loading") return <section className="system-evidence-status loading" aria-live="polite"><i /><div><small>SYSTEM EVIDENCE SNAPSHOT</small><strong>Validating the versioned System snapshot</strong><span>Architecture content remains available while its evidence envelope is checked.</span></div><b>CHECKING</b></section>;
  if (state === "failed" || !evidence) return <section className="system-evidence-status failed" aria-live="assertive"><i /><div><small>SYSTEM EVIDENCE SNAPSHOT</small><strong>Snapshot unavailable — status details withheld</strong><span>The AWS and OPS tabs will not substitute unvalidated service or reliability values.</span></div><b>FAIL CLOSED</b></section>;
  const runtimeEvidence = evidence.evidence_class === "AWS_RUNTIME_INSPECTION";
  return <section className="system-evidence-status connected" aria-live="polite"><i /><div><small>SYSTEM EVIDENCE SNAPSHOT</small><strong>{runtimeEvidence ? "Aggregate AWS runtime observation verified for display" : "Repository architecture verified for display"}</strong><span>As of {evidence.as_of_date} · {evidence.evidence_class.replaceAll("_", " ")} · live AWS inspection: {runtimeEvidence ? "yes — projected offline" : "no"}</span></div><b>READ ONLY</b></section>;
}

function SystemSectionTitle({ eyebrow, title, copy, badge }: { eyebrow: string; title: string; copy: string; badge: string }) {
  return <div className="system-section-title"><div><small>{eyebrow}</small><h2>{title}</h2><p>{copy}</p></div><b>{badge}</b></div>;
}

function SystemDailyFlow() {
  const steps = [
    ["01", "Ingest synthetic signals", "Shipment, port, disruption, and lifecycle evidence enters the governed analytics boundary.", "S3 + Glue"],
    ["02", "Detect abnormal conditions", "Athena and Iceberg aggregates identify cutoff-eligible conditions that require review.", "Athena"],
    ["03", "Explain business exposure", "Deterministic logic connects the condition to fee, inventory, SLA, or cost context.", "Rules"],
    ["04", "Recommend a bounded response", "Decision Briefs expose the selected rule, alternatives, and unavailable estimates without inventing value.", "Decision"],
    ["05", "Require named-human review", "Approve, edit, or reject is accepted only from signed identity claims in the private cockpit.", "Human gate"],
    ["06", "Append governed evidence", "The immutable proposal remains unchanged while idempotent audit events advance Action state.", "Action"],
    ["07", "Observe and learn cautiously", "Delayed simulated Outcomes can supply review evidence; they do not prove causal or real logistics performance.", "Outcome"],
  ];
  return <section className="system-section" aria-label="Daily E2E Flow">
    <SystemSectionTitle eyebrow="DAILY E2E FLOW" title="Signal to governed learning evidence" copy="The business path and AWS path stay aligned without giving the interface operational execution authority." badge="SYNTHETIC LOGISTICS" />
    <div className="system-flow-legend"><span><b>Business</b> Signal → Decision → Action → Outcome</span><span><b>AWS</b> S3 → Glue → Athena → Lambda</span><span><b>Control</b> Human review before mutation</span></div>
    <div className="system-flow-list">
      {steps.map(([number, title, copy, service]) => <article key={number}>
        <span>{number}</span><div><h3>{title}</h3><p>{copy}</p></div><b>{service}</b>
      </article>)}
    </div>
    <div className="system-callout"><strong>Two runtime tracks</strong><p>Production uses a success-gated scheduled aggregate path. Stateful multimodal staging is manually invoked, has no production alias or recurring schedule, and cannot write production tables.</p></div>
  </section>;
}

function SystemAwsOverview({ evidence, state }: {
  evidence: SystemEvidenceSnapshot | null;
  state: "loading" | "connected" | "failed";
}) {
  const runtimeEvidence = evidence?.evidence_class === "AWS_RUNTIME_INSPECTION";
  return <section className="system-section" aria-label="AWS Overview">
    <SystemSectionTitle eyebrow="AWS OVERVIEW" title="Deployed service responsibilities" copy={runtimeEvidence ? "A separately collected aggregate observation verified these service responsibilities without publishing resource identifiers or counts." : "This inventory preserves verified architecture without presenting historical resource counts as current live status."} badge={runtimeEvidence ? "RUNTIME EVIDENCE" : "REPOSITORY EVIDENCE"} />
    {state === "connected" && evidence
      ? <div className="system-service-grid">{evidence.services.map((service) => <article className="card" key={service.key}><small>{service.key}</small><h3>{service.label}</h3><p>{service.responsibility}</p><span>{service.status.replaceAll("_", " ")}</span></article>)}</div>
      : <DataState kind={state === "loading" ? "loading" : "failed"} title={state === "loading" ? "Validating service inventory" : "Service inventory withheld"} message={state === "loading" ? "The versioned System evidence snapshot is being checked." : "The snapshot failed validation, so no service status is substituted from page code."} />}
    <div className="system-boundary-grid">
      <article><small>PRODUCTION TRACK</small><strong>Scheduler → prod alias → governed aggregates</strong><p>Production automation targets an immutable alias. Movement of that alias remains a separately controlled human action.</p></article>
      <article><small>ISOLATED STAGING</small><strong>Manual controller → lifecycle history → private cockpit</strong><p>No Scheduler, production alias, or production-table write permission exists in the staging stack.</p></article>
    </div>
    <div className="system-callout historical"><strong>Historical counts intentionally withheld</strong><p>The older System page displayed an inspected 6 August 2026 resource inventory. Those counts are preserved in repository history; this browser view never calls AWS directly and does not publish them as current.</p></div>
  </section>;
}

function SystemDataCatalog() {
  const domains = [
    ["OPERATE", "Shipment and route state", ["fact_shipment_events_extended_iceberg", "fact_shipment_lifecycle_staging_v1"]],
    ["DETECT", "Alerts and operational signals", ["fact_ai_alerts_v3", "fact_shipment_signal_candidate_staging_v1"]],
    ["EXPLAIN", "Root cause and decision context", ["fact_ai_root_causes_v1", "fact_ai_insights_v3"]],
    ["DECIDE", "Deterministic recommendations", ["fact_ai_decisions_v3", "ai_decision_trace_v1"]],
    ["ACT", "Governed Action evidence", ["fact_ai_actions_v2", "current Action view"]],
    ["OBSERVE", "Outcome and learning evidence", ["fact_ai_outcomes_v2", "fact_ai_learning_feedback_v1"]],
  ];
  return <section className="system-section" aria-label="Data Catalog">
    <SystemSectionTitle eyebrow="DATA CATALOG" title="Governed decision domains" copy="Current public analytics use the v3/v2 decision flywheel; staging lifecycle contracts remain isolated and entity identifiers remain private." badge="AGGREGATE SAFE" />
    <div className="system-domain-grid">
      {domains.map(([label, title, assets]) => <article className="card" key={String(label)}><small>{label}</small><h3>{title}</h3><div>{(assets as string[]).map((asset) => <code key={asset}>{asset}</code>)}</div></article>)}
    </div>
    <div className="system-catalog-boundaries">
      <article><b>Published contract</b><p>Aggregate counts, freshness, distributions, forecast baselines, quality states, and allowlisted mode/provider/lane labels only.</p></article>
      <article><b>Private contract</b><p>Shipment and Action identifiers, signed actors, audit events, infrastructure values, and authenticated entity drill-down.</p></article>
      <article><b>Historical only</b><p>The legacy v1 anomaly, root-cause, and decision tables remain implementation history and cannot claim current daily pipeline health.</p></article>
    </div>
  </section>;
}

function SystemLogic() {
  const contracts = [
    ["Cutoff safety", "Only evidence at or before the Sydney business date can enter operational actual-calendar views."],
    ["Deterministic decision", "Rules select a bounded response and preserve alternatives; learned models cannot replace safety rules."],
    ["Exact binding", "A proposed Action binds to its Decision Brief version, selected alternative, and deterministic rationale."],
    ["Append-only state", "Proposal rows remain immutable; idempotent audit events record edit, approve, reject, and complete transitions."],
    ["Outcome boundary", "Delayed simulated Outcomes support engineering review but never become causal or real-performance evidence."],
    ["Forecast gate", "At least 28 eligible dates and seven rolling holdouts are required before advisory accuracy can be displayed."],
  ];
  return <section className="system-section" aria-label="Logic and SQL">
    <SystemSectionTitle eyebrow="LOGIC & SQL" title="Fail-closed decision contracts" copy="The interface explains governed calculations and table relationships without executing SQL or exposing query text, IDs, or result locations." badge="DETERMINISTIC FIRST" />
    <div className="system-contract-list">
      {contracts.map(([title, copy], index) => <article key={title}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{title}</strong><p>{copy}</p></div><b>ENFORCED</b></article>)}
    </div>
    <div className="system-callout"><strong>SQL boundary</strong><p>Athena performs governed aggregate and Iceberg operations behind validated adapters. The public interface presents contracts and safe results only; it cannot submit a query.</p></div>
  </section>;
}

function SystemOps({ go, evidence, state }: {
  go: (view: View) => void;
  evidence: SystemEvidenceSnapshot | null;
  state: "loading" | "connected" | "failed";
}) {
  const stages = ["Generation", "Lakehouse ingestion", "Input validation", "Decision pipeline", "Decision flywheel", "Output validation"];
  return <section className="system-section" aria-label="OPS Dashboard">
    <SystemSectionTitle eyebrow="OPS DASHBOARD" title="Reliability and recovery controls" copy="A run is current only after the exact six-stage sequence and all ten input/output quality checks succeed." badge="FAIL CLOSED" />
    {state === "connected" && evidence ? <>
      <div className="system-stage-strip">{stages.map((stage, index) => <article key={stage}><span>{index + 1}</span><strong>{stage}</strong></article>)}</div>
      <div className="system-ops-grid">
        <article className="card"><small>QUALITY GATES</small><h3>{evidence.reliability.quality_check_count} required checks</h3><p>Missing dates, empty inputs, duplicate keys, abnormal volume, and stale outputs are checked at both input and output boundaries.</p></article>
        <article className="card"><small>RECOVERY</small><h3>{evidence.reliability.retry_count} retries · {evidence.reliability.max_event_age_hours}h event age</h3><p>Exhausted scheduled failures enter the encrypted {evidence.reliability.dlq_retention_days}-day DLQ; recovery must finish with a governed rerun.</p></article>
        <article className="card"><small>OBSERVABILITY</small><h3>Safe operational evidence</h3><p>Logs and alarms cover start, counts, failures, throttles, duration, and DLQ state without publishing sensitive entity data.</p></article>
      </div>
    </> : <DataState kind={state === "loading" ? "loading" : "failed"} title={state === "loading" ? "Validating reliability controls" : "Reliability values withheld"} message={state === "loading" ? "The versioned System evidence snapshot is being checked." : "The snapshot failed validation, so stage and recovery values are not displayed."} />}
    <div className="system-action-row">
      <button className="outline-button" onClick={() => go("health")}>Open Pipeline Health</button>
      <button className="outline-button" onClick={() => go("forecasts")}>Open Forecast Accuracy</button>
      <button className="outline-button" onClick={() => go("actions")}>Open Action Board</button>
    </div>
    <div className="system-callout historical"><strong>No live health claim here</strong><p>The public Pipeline Health walkthrough explains controls. Current, stale, partial, or failed operational evidence is available only in the authenticated staging cockpit.</p></div>
  </section>;
}

function SystemRelease() {
  const release = ["Git commit", "CI checks", "GitHub OIDC", "Candidate", "Read-only dry-run", "Immutable version", "staging alias"];
  return <section className="system-section" aria-label="Release and Lineage">
    <SystemSectionTitle eyebrow="RELEASE & LINEAGE" title="Delivery without production authority" copy="Short-lived GitHub credentials can prepare and validate a candidate while production promotion stays outside the automated staging path." badge="HUMAN CONTROLLED" />
    <div className="system-release-flow">{release.map((item, index) => <Fragment key={item}><article><span>{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong></article>{index < release.length - 1 && <b>→</b>}</Fragment>)}</div>
    <div className="system-boundary-grid release">
      <article><small>STAGING AUTHORITY</small><strong>Candidate, dry-run, immutable version, staging alias</strong><p>The scoped deployer cannot update prod, administer IAM, modify Scheduler, or deploy unrelated functions.</p></article>
      <article><small>SEPARATE HUMAN AUTHORITY</small><strong>Production, schedules, infrastructure, policies, models</strong><p>Each requires its own explicit approval. Successful tests or a source publication do not grant that authority.</p></article>
    </div>
    <div className="system-lineage-grid">
      <article><small>SIGNAL</small><strong>Alert + insight</strong><p>Aggregate or authenticated evidence identifies a reviewable condition.</p></article>
      <article><small>DECISION</small><strong>Brief + alternative</strong><p>Deterministic rationale binds the proposed response.</p></article>
      <article><small>ACTION</small><strong>Proposal + audit</strong><p>Named-human events advance state without rewriting the proposal.</p></article>
      <article><small>LEARNING</small><strong>Outcome + proposal</strong><p>Evidence may create a pending proposal; activation is never automatic.</p></article>
    </div>
  </section>;
}

function Overview({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="Thursday, 23 July · 09:42 AEST" title="Good morning, Mia." copy="Here is what needs attention across your logistics network." action={<span className="outline-button static-control">Fixed walkthrough</span>} />
    <section className="metric-grid">
      <Metric label="Critical signals" value="3" note="+2 since yesterday" tone="red" />
      <Metric label="Pending decisions" value="3" note="1 due within 3 hours" tone="amber" />
      <Metric label="Cost exposure" value="$37.4k" note="Across active events" />
      <Metric label="Inventory at risk" value="6 SKUs" note="2 critical shortages" />
      <Metric label="Protected this month" value="$128k" note="+18% vs last month" tone="green" />
    </section>
    <section className="overview-grid">
      <article className="card network-card">
        <CardHead title="Network risk picture" copy="Live operational exposure by location" action={<button onClick={() => go("signals")}>View all signals →</button>} />
        <div className="network-map">
          <div className="map-grid" />
          <div className="ocean-label">ASIA–PACIFIC NETWORK</div>
          <Port x="15%" y="37%" name="Shanghai" level="medium" />
          <Port x="34%" y="58%" name="Singapore" level="high" />
          <Port x="79%" y="66%" name="Brisbane" level="high" />
          <Port x="74%" y="81%" name="Sydney" level="critical" />
          <Port x="65%" y="88%" name="Melbourne" level="low" />
          <div className="route-arc arc-one" /><div className="route-arc arc-two" />
        </div>
        <div className="map-legend"><span><i className="critical" /> Critical</span><span><i className="high" /> High</span><span><i className="medium" /> Medium</span><span><i className="low" /> Stable</span></div>
      </article>
      <article className="card attention-card">
        <CardHead title="Needs your attention" copy="Decisions ranked by urgency" action={<button onClick={() => go("decisions")}>Decision queue →</button>} />
        <button className="attention-item critical-item" data-claim-id="next-decision-recommendation" data-claim-classification="ILLUSTRATIVE" onClick={() => go("brief")}>
          <span className="severity">CRITICAL</span><small>Due in 2h 14m</small>
          <strong>Divert 8 FCL via Melbourne</strong>
          <p>Illustrative scenario recommendation · Sydney congestion and strike assumptions threaten critical inventory.</p>
          <div><span>12 FCL exposed</span><b>Protect $5,760 →</b></div>
        </button>
        <button className="attention-item" onClick={() => go("signals")}>
          <span className="severity high">HIGH</span><small>Due in 6h 30m</small>
          <strong>Expedite critical SKU replenishment</strong>
          <p>Brisbane DC inventory cover has fallen below threshold.</p>
          <div><span>3 SKUs exposed</span><b>Review →</b></div>
        </button>
      </article>
      <article className="card activity-card">
        <CardHead title="Signal activity" copy="New events detected over the last 7 days" />
        <div className="activity-bars">{[38,52,44,69,55,82,64].map((height, i) => <div key={i}><i style={{height:`${height}%`}} /><span>{["Fri","Sat","Sun","Mon","Tue","Wed","Thu"][i]}</span></div>)}</div>
        <div className="activity-summary"><div><strong>38</strong><span>Signals detected</span></div><div><strong>9</strong><span>Required decisions</span></div><div><strong>4.2h</strong><span>Average response</span></div></div>
      </article>
      <article className="card value-card" data-claim-id="next-portfolio-value" data-claim-classification="ILLUSTRATIVE">
        <CardHead title="Illustrative scenario value" copy="Fixed illustrative portfolio · not execution evidence" action={<button onClick={() => go("outcomes")}>View scenarios →</button>} />
        <div className="value-hero"><span>Illustrative portfolio</span><strong>$128,400</strong><small>modelled cost and loss avoidance</small></div>
        <div className="value-list"><span><i />Storage & demurrage <b>$46.2k</b></span><span><i />Stockout avoidance <b>$61.8k</b></span><span><i />Freight optimisation <b>$20.4k</b></span></div>
      </article>
    </section>
  </div>;
}

function Signals({ filter, setFilter, go, openBrief, risks, operationsState, operationsMessage, refresh }: {
  filter: string;
  setFilter: (v: string) => void;
  go: (view: View) => void;
  openBrief: (brief: DecisionBriefV1) => void;
  risks: OperationsRisk[];
  operationsState: OperationsLoadState;
  operationsMessage: string;
  refresh: () => Promise<void>;
}) {
  const visible = filter === "All" ? signals : signals.filter((signal) => signal.severity === filter);
  const visibleRisks = filter === "All" ? risks : risks.filter((risk) => risk.severity === filter.toUpperCase());
  if (operationsState !== "demo") return <div className="page">
    <PageTitle eyebrow="DETECT" title="Risk hotspots" copy="Authenticated operational Alerts ranked for human review." action={<button className="outline-button" onClick={() => void refresh()}>Refresh risks</button>} />
    <div className="toolbar"><div className="filters">{["All","Critical","High","Medium"].map((item) => <button className={filter === item ? "active" : ""} onClick={() => setFilter(item)} key={item}>{item}{item === "All" && ` ${risks.length}`}</button>)}</div></div>
    <OperationsState state={operationsState} message={operationsMessage} label="risk hotspots" onRetry={refresh} />
    {operationsState === "connected" && <div className="table-card">
      <div className="data-row table-head"><span>Risk</span><span>Alert</span><span>Current reading</span><span>Exposure</span><span>Detected</span><span /></div>
      {visibleRisks.map((risk) => <button className="data-row" key={risk.alert_fingerprint} onClick={() => risk.decision_brief ? openBrief(risk.decision_brief) : go("decisions")}>
        <span><b className={`risk-pill ${risk.severity.toLowerCase()}`}>{risk.severity}</b></span>
        <span><strong>{risk.alert_type.replaceAll("_", " ")}</strong><small>{risk.alert_grain} · {risk.alert_dimension}</small></span>
        <span><strong>{risk.metric_value}</strong><small>Threshold {risk.threshold_value}</small></span>
        <span>Shipment {risk.shipment_id}</span><span>{risk.last_detected_date}</span><span className="row-link">→</span>
      </button>)}
      {visibleRisks.length === 0 && <DataState kind="empty" title="No matching risk hotspots" message="No open operational Risks match this filter. Change the severity filter or refresh the latest evidence." />}
    </div>}
  </div>;
  return <div className="page">
    <PageTitle eyebrow="DETECT" title="Signal monitoring" copy="See emerging risks before they become operational disruption." action={<span className="outline-button static-control">4 illustrative sources</span>} />
    <div className="toolbar"><div className="filters">{["All","Critical","High","Medium"].map((f) => <button className={filter === f ? "active" : ""} onClick={() => setFilter(f)} key={f}>{f}{f === "All" && " 4"}</button>)}</div><label className="search">⌕<input placeholder="Search signals" /></label></div>
    <div className="table-card">
      <div className="data-row table-head"><span>Risk</span><span>Signal</span><span>Current reading</span><span>Exposure</span><span>Detected</span><span /></div>
      {visible.map((signal) => <button className="data-row" key={signal.title} onClick={() => go("brief")}>
        <span><b className={`risk-pill ${signal.severity.toLowerCase()}`}>{signal.severity}</b></span>
        <span><strong>{signal.title}</strong><small>{signal.source}</small></span>
        <span><strong>{signal.value}</strong></span><span>{signal.affected}</span><span>{signal.time}</span><span className="row-link">→</span>
      </button>)}
    </div>
  </div>;
}

function Decisions({ go, actions, operationsState, operationsMessage, reviewHandoffMessage, reviewAction, refresh }: {
  go: (view: View) => void;
  actions: OperationsAction[];
  operationsState: OperationsLoadState;
  operationsMessage: string;
  reviewHandoffMessage: string;
  reviewAction: (action: OperationsAction) => void;
  refresh: () => Promise<void>;
}) {
  const [severityFilter, setSeverityFilter] = useState<DecisionSeverityFilter>("ALL");
  const waitingActions = waitingDecisionActions(actions);
  const visibleActions = filterDecisionQueue(actions, severityFilter);
  if (operationsState === "demo") return <DemoDecisions go={go} />;
  return <div className="page">
    <PageTitle eyebrow="DECIDE" title="Decision queue" copy="Authenticated operational Actions ready for human review." action={<button className="outline-button" onClick={() => void refresh()}>Refresh queue</button>} />
    <div className="toolbar"><div className="filters" aria-label="Decision severity filter">{decisionSeverityFilters.map((severity) => <button aria-pressed={severityFilter === severity} className={severityFilter === severity ? "active" : ""} onClick={() => setSeverityFilter(severity)} key={severity}>{severity === "ALL" ? "All" : severity.charAt(0) + severity.slice(1).toLowerCase()} {decisionSeverityCount(actions, severity)}</button>)}</div></div>
    <OperationsState state={operationsState} message={operationsMessage} label="decision queue" onRetry={refresh} />
    {reviewHandoffMessage && <DataState kind="failed" title="Decision review handoff blocked" message={reviewHandoffMessage} />}
    {operationsState === "connected" && <div className="decision-list">
      {visibleActions.map((item) => <button className="decision-card" key={item.action_id} onClick={() => reviewAction(item)}>
        <div className={`decision-priority ${item.alert_severity.toLowerCase()}`}><i /><span>{item.alert_severity}</span></div>
        <div className="decision-main"><small>{item.action_id}</small><strong>{item.action_type.replaceAll("_", " ")}</strong><span>Shipment {item.shipment_id}</span><span>{item.decision_brief_version ? `Bound to ${item.decision_brief_version}` : "Legacy proposal — no Decision Brief binding"}</span></div>
        <div className="decision-value"><small>Alert</small><strong>{item.alert_type.replaceAll("_", " ")}</strong></div>
        <div className="decision-due"><small>{item.action_due_date ? "Due" : "Created"}</small><strong>{item.action_due_date ?? item.created_date}</strong></div>
        <span className="status-button">Review now</span>
      </button>)}
      {waitingActions.length === 0 && <DataState kind="empty" title="Decision queue is clear" message="No Actions are waiting for human review at this Sydney cutoff." />}
      {waitingActions.length > 0 && visibleActions.length === 0 && <DataState kind="empty" title={`No ${severityFilter.toLowerCase()} Decisions`} message="No waiting Actions match this severity. Choose another filter or refresh the queue." />}
    </div>}
  </div>;
}

function DemoDecisions({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="DECIDE" title="Decision queue" copy="Prioritised recommendations ready for human review." action={<span className="outline-button static-control">3 illustrative items</span>} />
    <div className="queue-summary"><span><strong>3</strong>Waiting for review</span><span><strong>1</strong>Due within 3 hours</span><span><strong>$27.4k</strong>Potential value</span></div>
    <div className="decision-list">{decisions.map((item) => <button className="decision-card" key={item.id} onClick={() => go("brief")}>
      <div className={`decision-priority ${item.priority.toLowerCase()}`}><i /><span>{item.priority}</span></div>
      <div className="decision-main"><small>{item.id}</small><strong>{item.title}</strong><span>Owner · {item.owner}</span></div>
      <div className="decision-value"><small>Modelled value</small><strong>{item.value}</strong></div>
      <div className="decision-due"><small>Decision window</small><strong>{item.due}</strong></div>
      <span className="status-button">{item.status} →</span>
    </button>)}</div>
  </div>;
}

function ActionBoard({ actions, focusedActionId, clearFocusedAction, backToDecisionBrief, openDecisionQueue, operationsState, operationsMessage, submitOperation, refresh }: {
  actions: OperationsAction[];
  focusedActionId: string | null;
  clearFocusedAction: () => void;
  backToDecisionBrief: () => void;
  openDecisionQueue: () => void;
  operationsState: OperationsLoadState;
  operationsMessage: string;
  submitOperation: (actionId: string, operation: ActionOperation, reason: string, assignment?: { actionOwner?: string; actionDueDate?: string }) => Promise<boolean>;
  refresh: () => Promise<void>;
}) {
  const [reason, setReason] = useState("Reviewed current operational evidence");
  const [actionOwner, setActionOwner] = useState("");
  const [actionDueDate, setActionDueDate] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState("");
  const [evidence, setEvidence] = useState<ActionEvidence | null>(null);
  const [evidenceState, setEvidenceState] = useState<"idle" | "loading" | "connected" | "error">("idle");
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const focusedAction = focusedActionId
    ? actions.find((item) => item.action_id === focusedActionId) ?? null
    : null;
  const visibleActions = focusedActionId ? (focusedAction ? [focusedAction] : []) : actions;
  const reviewEvidence = async (actionId: string, forceRefresh = false) => {
    if (!forceRefresh && selectedEvidence === actionId && evidenceState === "connected") {
      setSelectedEvidence("");
      setEvidence(null);
      setEvidenceState("idle");
      return;
    }
    setSelectedEvidence(actionId);
    setEvidence(null);
    setEvidenceState("loading");
    try {
      setEvidence(await loadActionEvidence(readOperationsToken(), actionId));
      setEvidenceState("connected");
      setEvidenceMessage("");
    } catch (error) {
      setEvidenceState("error");
      setEvidenceMessage(error instanceof Error ? error.message : "Unable to load the Action evidence chain");
    }
  };
  const run = async (action: OperationsAction, operation: ActionOperation) => {
    setBusyAction(action.action_id);
    try {
      const succeeded = await submitOperation(
        action.action_id, operation, reason,
        operation === "EDIT" ? { actionOwner, actionDueDate } : {},
      );
      if (succeeded && selectedEvidence === action.action_id) {
        await reviewEvidence(action.action_id, true);
      }
    }
    finally { setBusyAction(""); }
  };
  if (operationsState === "demo") return <DemoActionBoard openDecisionBrief={backToDecisionBrief} openDecisionQueue={openDecisionQueue} />;
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Action Board" copy="Move approved operational Actions through their governed lifecycle." action={<button className="outline-button" onClick={() => void refresh()}>Refresh board</button>} />
    <OperationsState state={operationsState} message={operationsMessage} label="Action Board" onRetry={refresh} />
    {operationsState === "connected" && <>
      {focusedActionId && !focusedAction && <DataState kind="failed" title="Selected Action unavailable" message="The selected Action is no longer present in the authenticated queue. No mutation is available from this review handoff." action={<button className="outline-button" onClick={clearFocusedAction}>Show all Actions</button>} />}
      {focusedAction && <section className="review-handoff-banner" role="status">
        <div><small>Selected Decision review</small><strong>Only the Action whose bound Brief you just reviewed is shown.</strong><span>Its immutable binding was reconciled before this page opened; no mutation or evidence query ran automatically.</span></div>
        <div className="review-handoff-actions"><button className="outline-button" onClick={backToDecisionBrief}>Back to bound Decision Brief</button><button className="outline-button" onClick={clearFocusedAction}>Show all Actions</button></div>
      </section>}
      {visibleActions.length === 0 && !focusedActionId
        ? <DataState kind="empty" title="No governed Actions" message="There are no Actions available for this authenticated role and cutoff." />
        : visibleActions.length > 0 && <><label className="select-label"><span>Audit reason for the next update</span><input className="operations-reason" value={reason} minLength={3} maxLength={500} onChange={(event) => setReason(event.target.value)} /></label>
        <label className="select-label"><span>Named Action owner (used by Edit)</span><input className="operations-reason" value={actionOwner} maxLength={128} onChange={(event) => setActionOwner(event.target.value)} /></label>
        <label className="select-label"><span>Action due date (used by Edit)</span><input className="operations-reason" type="date" value={actionDueDate} onChange={(event) => setActionDueDate(event.target.value)} /></label>
        <div className="decision-list">{visibleActions.map((item) => <article className="decision-card" key={item.action_id}>
        <div className={`decision-priority ${item.alert_severity.toLowerCase()}`}><i /><span>{item.alert_severity}</span></div>
        <div className="decision-main"><small>{item.action_id}</small><strong>{item.action_type.replaceAll("_", " ")}</strong><span>{item.alert_type.replaceAll("_", " ")} · Shipment {item.shipment_id}</span><span>Owner: {item.action_owner ?? "Unassigned"} · Due: {item.action_due_date ?? "Not set"}</span><span>{item.decision_brief_version ? `${item.decision_brief_version} · Selected ${item.selected_alternative?.replaceAll("_", " ")}` : "Legacy proposal — no Decision Brief binding"}</span>{item.selection_rationale && <span>{item.selection_rationale}</span>}</div>
        <div className="decision-value"><small>Status</small><strong>{item.status}</strong></div>
        <div className="decision-buttons">
          <button disabled={evidenceState === "loading" && selectedEvidence === item.action_id} onClick={() => void reviewEvidence(item.action_id)}>{selectedEvidence === item.action_id && evidenceState === "connected" ? "Hide evidence" : "Evidence chain"}</button>
          {item.status === "PROPOSED" && <><button disabled={busyAction === item.action_id || reason.trim().length < 3 || actionOwner.trim().length < 2 || !actionDueDate} onClick={() => void run(item, "EDIT")}>Assign &amp; edit</button><button disabled={busyAction === item.action_id || reason.trim().length < 3} onClick={() => void run(item, "REJECT")}>Reject</button><button disabled={busyAction === item.action_id || reason.trim().length < 3} onClick={() => void run(item, "APPROVE")}>Approve</button></>}
          {item.status === "EDITED" && <><button disabled={busyAction === item.action_id || reason.trim().length < 3} onClick={() => void run(item, "REJECT")}>Reject</button><button disabled={busyAction === item.action_id || reason.trim().length < 3} onClick={() => void run(item, "APPROVE")}>Approve</button></>}
          {item.status === "APPROVED" && <button disabled={busyAction === item.action_id || reason.trim().length < 3} onClick={() => void run(item, "COMPLETE")}>Mark complete</button>}
          {(item.status === "REJECTED" || item.status === "COMPLETED") && <span className="status-button">Closed</span>}
        </div>
        {selectedEvidence === item.action_id && <section className="action-evidence" aria-live="polite" aria-busy={evidenceState === "loading"}>
          {evidenceState === "loading" && <DataState kind="loading" title="Loading Action evidence" message="Joining the immutable proposal, append-only audit events, and eligible Outcome." />}
          {evidenceState === "error" && <DataState kind="failed" title="Action evidence unavailable" message={evidenceMessage} onRetry={() => reviewEvidence(item.action_id)} />}
          {evidenceState === "connected" && evidence && <>
            <header><div><small>Action–Outcome evidence chain</small><strong>{evidence.chain_status.replaceAll("_", " ")}</strong></div><span>Sydney cutoff {evidence.as_of_date}</span></header>
            <div className="action-evidence-flow">
              <article><small>Immutable proposal</small><strong>{evidence.action.action_type.replaceAll("_", " ")}</strong><span>{evidence.action.created_date} · {evidence.action.status}</span><span>{evidence.action.decision_brief_version ? `${evidence.action.decision_brief_version} · ${evidence.action.selected_alternative?.replaceAll("_", " ")}` : "Legacy proposal — binding unavailable"}</span>{evidence.action.selection_rationale && <span>{evidence.action.selection_rationale}</span>}</article>
              <div className="action-audit-events">{evidence.events.length
                ? evidence.events.map((event) => <article key={event.event_id}><i /><div><small>{event.occurred_at}</small><strong>{event.event_type}: {event.previous_status} → {event.new_status}</strong><span>{event.actor} · {event.reason}</span></div></article>)
                : <p>No human mutation has been recorded; the proposal remains unchanged.</p>}
              </div>
              <article className={evidence.outcome?.evidence_status === "OBSERVED_ACTUAL_CALENDAR" ? "observed" : "pending"}><small>Simulated Outcome</small><strong>{evidence.outcome ? evidence.outcome.outcome_status.replaceAll("_", " ") : "Not created"}</strong><span>{evidence.outcome?.evidence_status === "OBSERVED_ACTUAL_CALENDAR" ? `Observed ${evidence.outcome.observed_date} · ${evidence.outcome.effect_pct}% effect` : evidence.outcome ? `Due ${evidence.outcome.observation_due_date} · not observed` : "Requires an approved, completed Action"}</span></article>
            </div>
            <p className="data-disclaimer">The proposal is immutable and audit events are append-only. The Decision Brief version, selected deterministic alternative, and proposal rationale are immutable. Named-human review reasons remain append-only audit events. Outcomes are reproducible synthetic staging evidence, never real logistics performance.</p>
          </>}
        </section>}
      </article>)}</div></>}
    </>}
  </div>;
}

function DemoActionBoard({ openDecisionBrief, openDecisionQueue }: {
  openDecisionBrief: () => void;
  openDecisionQueue: () => void;
}) {
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Action Board" copy="Follow an illustrative Action from proposal through human review to a delayed Outcome." action={<button className="outline-button" onClick={openDecisionQueue}>Open decision queue</button>} />
    <section className="demo-boundary" role="status">
      <div><small>Public walkthrough</small><strong>Read-only lifecycle preview</strong><span>These cards explain the governed workflow. They do not call the Operations API or send instructions to a carrier, terminal, or warehouse.</span></div>
      <b>NO WRITES</b>
    </section>
    <section className="metric-grid compact">
      <Metric label="Lifecycle steps" value="3" note="Proposal, review, Outcome" />
      <Metric label="Human decision gates" value="2" note="Approve or reject" />
      <Metric label="Automatic execution" value="0" note="Always disabled" tone="green" />
      <Metric label="Evidence mode" value="Illustrative" note="Not operational status" tone="amber" />
    </section>
    <section className="demo-lifecycle-grid" aria-label="Illustrative Action lifecycle">
      <article><span>1</span><div><small>Immutable proposal</small><strong>Decision becomes an Action</strong><p>The recommendation, selected alternative, and rationale are fixed before review.</p></div></article>
      <article><span>2</span><div><small>Named-human review</small><strong>Approve, reject, or edit</strong><p>Every change becomes an append-only audit event; the public walkthrough cannot perform it.</p></div></article>
      <article><span>3</span><div><small>Delayed evidence</small><strong>Observe an Outcome later</strong><p>A completed Action can create a synthetic pending Outcome, which remains separate from real performance.</p></div></article>
    </section>
    <article className="card demo-action-example">
      <CardHead title="Illustrative Action ready for review" copy="One fixed example connects the Decision Brief to the governed Action lifecycle." />
      <div className="decision-card demo-action-card">
        <div className="decision-priority critical"><i /><span>Critical</span></div>
        <div className="decision-main"><small>ILLUSTRATIVE ACTION</small><strong>Divert 8 FCL via Melbourne</strong><span>Bound to the fixed port-disruption Decision Brief</span></div>
        <div className="decision-value"><small>Status</small><strong>Proposed</strong></div>
        <div className="decision-due"><small>Authority</small><strong>Human review</strong></div>
        <button className="primary-button" onClick={openDecisionBrief}>Review illustrative brief</button>
      </div>
    </article>
    <p className="data-disclaimer">Illustrative public content only. No Action is assigned, approved, rejected, completed, or executed from this page.</p>
  </div>;
}

function DataState({ kind, title, message, onRetry, action }: {
  kind: DataStateKind;
  title: string;
  message: string;
  onRetry?: () => void | Promise<void>;
  action?: React.ReactNode;
}) {
  const failed = kind === "failed";
  return <section
    className={`data-state ${kind}`}
    role={failed ? "alert" : "status"}
    aria-live={failed ? "assertive" : "polite"}
    aria-busy={kind === "loading"}
  >
    <span className="data-state-icon" aria-hidden="true" />
    <div><strong>{title}</strong><p>{message}</p></div>
    {(onRetry || action) && <div className="data-state-action">
      {onRetry && <button className="outline-button" onClick={() => void onRetry()}>Try again</button>}
      {action}
    </div>}
  </section>;
}

function OperationsState({ state, message, label, onRetry }: {
  state: OperationsLoadState;
  message: string;
  label: string;
  onRetry: () => void | Promise<void>;
}) {
  if (state === "connected" || state === "demo") return null;
  if (state === "loading") return <DataState kind="loading" title={`Loading ${label}`} message="Retrieving authenticated operational evidence." />;
  if (state === "auth_required") return <DataState kind="auth_required" title="Internal sign-in required" message={message} />;
  return <DataState kind="failed" title={`${label} unavailable`} message={message} onRetry={onRetry} />;
}

function PipelineHealth({ health, state, message, refresh }: {
  health: PipelineHealthData | null;
  state: OperationsLoadState;
  message: string;
  refresh: () => Promise<void>;
}) {
  if (state === "demo") return <DemoPipelineHealth />;
  const label = (value: string) => value.replaceAll("_", " ");
  return <div className="page">
    <PageTitle eyebrow="RELIABILITY" title="Pipeline Health" copy="See where the latest operational run is healthy, delayed, or blocked before its data reaches decisions." action={<button className="outline-button" onClick={() => void refresh()}>Refresh health</button>} />
    <OperationsState state={state} message={message} label="Pipeline Health" onRetry={refresh} />
    {state === "connected" && health && <>
      {health.status === "failed" || health.failed_stage || health.freshness_status === "future_invalid"
        ? <DataState kind="failed" title="Pipeline evidence cannot be used" message={health.freshness_status === "future_invalid" ? "The run is dated after the current Sydney cutoff and is excluded from operational evidence." : health.failure_category ? label(health.failure_category) : "A required stage did not complete."} onRetry={refresh} action={<a href={health.runbook_url} target="_blank" rel="noreferrer">Open recovery runbook</a>} />
        : (health.status === "stale" || health.freshness_status === "stale")
          ? <DataState kind="stale" title="Pipeline evidence is stale" message={`The latest verified run is older than the ${health.as_of_date} Sydney cutoff.`} onRetry={refresh} />
          : (health.status === "running" || health.status === "unverified" || health.stages_succeeded < health.stage_count || health.quality_checks_succeeded < health.quality_checks_total)
            ? <DataState kind="partial" title="Pipeline evidence is only partially available" message="Some stages or quality checks have not produced verified evidence yet." onRetry={refresh} />
            : null}
      <section className="metric-grid compact">
        <Metric label="Run status" value={label(health.status)} note={`Freshness: ${label(health.freshness_status)}`} tone={health.status === "current" ? "green" : health.status === "failed" ? "red" : "amber"} />
        <Metric label="Stages succeeded" value={`${health.stages_succeeded}/${health.stage_count}`} note="Required execution order" />
        <Metric label="Quality checks" value={`${health.quality_checks_succeeded}/${health.quality_checks_total}`} note="Input and output gates" />
        <Metric label="Logical run date" value={health.logical_run_date ?? "Unverified"} note={`Sydney cutoff ${health.as_of_date}`} />
      </section>
      <section className="pipeline-stage-grid">
        {health.stages.map((stage, index) => <article className={`pipeline-stage ${stage.status}`} key={stage.name}>
          <div className="pipeline-stage-head"><span>{index + 1}</span><div><small>Stage {index + 1}</small><strong>{label(stage.name)}</strong></div><b>{label(stage.status)}</b></div>
          <dl><div><dt>Duration</dt><dd>{stage.duration_ms === null ? "—" : `${(stage.duration_ms / 1000).toFixed(1)}s`}</dd></div><div><dt>Completed</dt><dd>{stage.completed_at ? new Date(stage.completed_at).toLocaleString("en-AU", { timeZone: "Australia/Sydney" }) : "—"}</dd></div></dl>
          {stage.failure_category && <p className="pipeline-failure">{label(stage.failure_category)}</p>}
          {stage.quality_checks.length > 0 && <ul className="pipeline-checks">{stage.quality_checks.map((check) => <li key={check.name}><i className={check.status} />{label(check.name)}<b>{check.status}</b></li>)}</ul>}
        </article>)}
      </section>
      <p className="data-disclaimer">This view contains operational actual-calendar evidence only. Future simulations cannot be presented as current pipeline health.</p>
    </>}
  </div>;
}

function DemoPipelineHealth() {
  const stages = [
    ["Signal intake", "Collect synthetic shipment and disruption inputs."],
    ["Feature preparation", "Create cutoff-safe aggregates for detection."],
    ["Anomaly detection", "Identify conditions that require review."],
    ["Decision generation", "Apply deterministic, explainable rules."],
    ["Input validation", "Fail closed when required evidence is incomplete."],
    ["Output validation", "Release only when governed quality checks pass."],
  ];
  return <div className="page">
    <PageTitle eyebrow="RELIABILITY" title="Pipeline Health" copy="Understand the six gates that must pass before synthetic operational evidence can reach a decision." />
    <section className="demo-boundary" role="status">
      <div><small>System walkthrough</small><strong>No live health status is exposed</strong><span>The public view explains the control flow without revealing private stages, infrastructure identifiers, timestamps, alarms, or runbooks.</span></div>
      <b>ILLUSTRATIVE</b>
    </section>
    <section className="metric-grid compact">
      <Metric label="Governed stages" value="6" note="Required sequence" />
      <Metric label="Quality checks" value="10" note="Input and output gates" />
      <Metric label="Live stages shown" value="0" note="Private by design" tone="green" />
      <Metric label="Failure policy" value="Fail closed" note="No partial health claim" tone="amber" />
    </section>
    <section className="pipeline-stage-grid">{stages.map(([name, purpose], index) => <article className="pipeline-stage illustrative" key={name}>
      <div className="pipeline-stage-head"><span>{index + 1}</span><div><small>Stage {index + 1}</small><strong>{name}</strong></div><b>Walkthrough</b></div>
      <p className="demo-stage-purpose">{purpose}</p>
    </article>)}</section>
    <DataState kind="idle" title="What the authenticated cockpit adds" message="Signed-in staging users can see current, stale, partial, or failed evidence and the exact quality gate that blocked a run. This public walkthrough never labels an illustrative stage as healthy." />
  </div>;
}

function ForecastAccuracy({ contract, state, message, refresh }: {
  contract: ForecastContract | null;
  state: OperationsLoadState;
  message: string;
  refresh: () => Promise<void>;
}) {
  if (state === "demo") return <DemoForecastAccuracy />;
  const metrics = contract?.accuracy.metrics;
  const maxForecast = Math.max(...(contract?.forecast.points.map((point) => point.upper_bound) ?? [1]), 1);
  return <div className="page">
    <PageTitle eyebrow="PLAN" title="Forecast Accuracy" copy="Review the advisory shipment-volume baseline and the evidence that limits how it may be used." action={<button className="outline-button" onClick={() => void refresh()}>Refresh forecast</button>} />
    <OperationsState state={state} message={message} label="Forecast Accuracy" onRetry={refresh} />
    {state === "connected" && contract && <>
      {(contract.forecast.status === "insufficient_operational_history" || contract.accuracy.status === "insufficient_operational_history") && <DataState kind="partial" title="Forecast evidence is incomplete" message={`Only ${contract.coverage.eligible_dates} of ${contract.coverage.window_days} eligible actual-calendar dates are available. Advisory projections and promotion evidence remain limited.`} />}
      <section className="forecast-boundary">
        <div><small>Evidence boundary</small><strong>Synthetic operational-calendar baseline</strong><span>Cut off at {contract.as_of_date}; future points remain unobserved projections.</span></div>
        <b>{contract.forecast.decision_use.replaceAll("_", " ")}</b>
      </section>
      <section className="metric-grid compact">
        <Metric label="Forecast status" value={contract.forecast.status === "ready" ? "Advisory ready" : "History pending"} note="Never an operational target" tone={contract.forecast.status === "ready" ? "green" : "amber"} />
        <Metric label="Backtest status" value={contract.accuracy.status === "engineering_evidence" ? "Engineering evidence" : "History pending"} note="Model promotion remains blocked" tone="amber" />
        <Metric label="MAE" value={metrics ? metrics.mae.toFixed(2) : "—"} note={metrics ? `${metrics.forecast_count} rolling holdouts` : `Requires ${contract.coverage.minimum_accuracy_forecasts} holdouts`} />
        <Metric label="Interval coverage" value={metrics ? `${metrics.interval_coverage_pct.toFixed(1)}%` : "—"} note="Synthetic engineering backtest" />
      </section>
      <section className="forecast-grid">
        <article className="card forecast-card"><CardHead title="Seven-day advisory projection" copy={`${contract.forecast.method.replaceAll("_", " ")} · ${contract.forecast.model_version}`} />
          {contract.forecast.points.length ? <div className="forecast-bars">{contract.forecast.points.map((point) => <div key={point.date}>
            <span><i style={{height: `${Math.max(8, point.predicted_shipments / maxForecast * 100)}%`}} /></span>
            <strong>{point.predicted_shipments}</strong><small>{point.date.slice(5)}</small>
          </div>)}</div> : <DataState kind="empty" title="No advisory projection yet" message="The actual-calendar window has not reached the 28 eligible dates required for an advisory projection." />}
        </article>
        <article className="card forecast-card"><CardHead title="Accuracy and readiness" copy="Rolling one-step-ahead evaluation using dates at or before the Sydney cutoff" />
          <dl className="forecast-metrics">
            <div><dt>Eligible calendar dates</dt><dd>{contract.coverage.eligible_dates}/{contract.coverage.window_days}</dd></div>
            <div><dt>RMSE</dt><dd>{metrics ? metrics.rmse.toFixed(2) : "—"}</dd></div>
            <div><dt>Bias</dt><dd>{metrics ? metrics.bias.toFixed(2) : "—"}</dd></div>
            <div><dt>MAPE</dt><dd>{metrics?.mape_pct === null || !metrics ? "—" : `${metrics.mape_pct.toFixed(1)}%`}</dd></div>
            <div><dt>Promotion</dt><dd className="blocked">{contract.accuracy.model_promotion_status}</dd></div>
            <div><dt>Production effect</dt><dd>{contract.forecast.production_effect ? "Enabled" : "None"}</dd></div>
          </dl>
        </article>
      </section>
      <p className="data-disclaimer">{contract.disclosure} Scenario: {contract.forecast.scenario_id}.</p>
    </>}
  </div>;
}

function DemoForecastAccuracy() {
  return <div className="page">
    <PageTitle eyebrow="PLAN" title="Forecast Accuracy" copy="See the evidence gates a forecast must clear before advisory accuracy can be displayed." />
    <section className="forecast-boundary demo-forecast-boundary">
      <div><small>Public walkthrough</small><strong>Readiness logic, not measured performance</strong><span>No forecast points, accuracy scores, or production predictions are presented as observed results.</span></div>
      <b>ILLUSTRATIVE</b>
    </section>
    <section className="metric-grid compact">
      <Metric label="History gate" value="28 dates" note="Actual-calendar coverage required" />
      <Metric label="Accuracy gate" value="7 holdouts" note="Rolling evaluations required" />
      <Metric label="Production effect" value="Blocked" note="Advisory only" tone="amber" />
      <Metric label="Promotion authority" value="Human" note="Never automatic" tone="green" />
    </section>
    <section className="forecast-grid demo-forecast-grid">
      <article className="card"><CardHead title="How evidence becomes displayable" copy="Each gate must be satisfied using cutoff-eligible actual-calendar evidence." />
        <ol className="demo-readiness-list">
          <li><span>1</span><div><strong>Build eligible history</strong><p>Future simulations and pending labels cannot fill the 28-date coverage window.</p></div></li>
          <li><span>2</span><div><strong>Run rolling holdouts</strong><p>At least seven one-step-ahead evaluations are required before accuracy metrics can appear.</p></div></li>
          <li><span>3</span><div><strong>Keep the decision bounded</strong><p>Passing engineering checks permits an advisory display only; it does not authorize model promotion or production control.</p></div></li>
        </ol>
      </article>
      <article className="card"><CardHead title="What remains hidden here" copy="The public walkthrough avoids pseudo-performance and private operational detail." />
        <dl className="forecast-metrics">
          <div><dt>Forecast points</dt><dd>Not shown</dd></div>
          <div><dt>MAE / RMSE / MAPE</dt><dd>Not claimed</dd></div>
          <div><dt>Operational cutoff</dt><dd>Private</dd></div>
          <div><dt>Model promotion</dt><dd className="blocked">Not authorised</dd></div>
        </dl>
      </article>
    </section>
    <p className="data-disclaimer">This page explains the governed forecast contract only. It does not establish measured accuracy, real logistics performance, label maturity, or production readiness.</p>
  </div>;
}

function Shipments({ go, contract, entities, state, message, shipmentState, selection, nextToken, refresh, openGroup, loadMore }: {
  go: (view: View) => void;
  contract: NetworkResponse | null;
  entities: ShipmentEntity[];
  state: OperationsLoadState;
  message: string;
  shipmentState: ShipmentLoadState;
  selection: NetworkSummary | null;
  nextToken: string | null;
  refresh: () => Promise<void>;
  openGroup: (selection: NetworkSummary) => Promise<void>;
  loadMore: () => Promise<void>;
}) {
  if (state === "demo") return <DemoShipments go={go} />;
  const rows = contract?.items ?? [];
  const total = rows.reduce((sum, item) => sum + Number(item.shipment_count), 0);
  const active = rows.reduce((sum, item) => sum + Number(item.active_shipment_count), 0);
  const breaches = rows.reduce((sum, item) => sum + Number(item.sla_breach_count), 0);
  const providers = new Set(rows.map((item) => item.provider_code)).size;
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Network Drill-down" copy="Move from provider and lane performance to the authorised shipment evidence behind it." action={<button className="outline-button" onClick={() => void refresh()}>Refresh network</button>} />
    <OperationsState state={state} message={message} label="Network Drill-down" onRetry={refresh} />
    {state === "connected" && contract && <>
      <section className="metric-grid compact">
        <Metric label="Latest shipments" value={String(total)} note={`Sydney cutoff ${contract.as_of_date}`} />
        <Metric label="Active" value={String(active)} note="Latest operational snapshot" />
        <Metric label="SLA breaches" value={String(breaches)} note="Actual-calendar evidence" tone={breaches ? "red" : "green"} />
        <Metric label="Providers" value={String(providers)} note={`${rows.length} provider-lane groups`} />
      </section>
      <section className="network-grid">
        <article className="card network-card"><CardHead title="Provider and lane summary" copy="Select a row to open its shipment entities when your role permits it." />
          <div className="network-summary-list">
            {rows.map((item) => <button key={`${item.transport_mode}-${item.provider_code}-${item.market_lane}`} disabled={!contract.entity_access} onClick={() => void openGroup(item)}>
              <span><b>{item.transport_mode}</b><strong>{item.provider_code}</strong><small>{item.market_lane}</small></span>
              <span><strong>{item.active_shipment_count}</strong><small>active / {item.shipment_count} total</small></span>
              <span><strong className={Number(item.sla_breach_count) ? "red-text" : "green-text"}>{item.sla_breach_count}</strong><small>{item.sla_breach_rate_pct}% SLA breach</small></span>
              <i>→</i>
            </button>)}
          </div>
          {!rows.length && <DataState kind="empty" title="No provider-lane evidence" message="No operational provider-lane rows are available at this Sydney cutoff." />}
          {!contract.entity_access && <p className="data-disclaimer">Your viewer role can inspect aggregate performance, but shipment identifiers require an operator, approver, or administrator role.</p>}
        </article>
        <article className="card network-card"><CardHead title="Shipment evidence" copy={selection ? `${selection.provider_code} · ${selection.market_lane}` : "Choose an authorised provider-lane row"} />
          {shipmentState === "loading" && <DataState kind="loading" title="Loading shipment evidence" message="Retrieving authorised entity records for the selected provider and lane." />}
          {shipmentState === "error" && <DataState kind="failed" title="Shipment evidence unavailable" message={message} onRetry={selection ? () => openGroup(selection) : undefined} />}
          {shipmentState === "partial" && <DataState kind="partial" title="Some shipment evidence is still available" message={`${message} Previously loaded rows remain visible.`} onRetry={loadMore} />}
          {shipmentState === "idle" && <DataState kind="idle" title="Choose a provider and lane" message="Entity records are not fetched until an authorised user selects a provider and lane." />}
          {entities.length > 0 && <div className="entity-list">{entities.map((item) => <article key={item.shipment_id}>
            <div><small>{item.transport_mode} · {item.market_lane}</small><strong>{item.shipment_id}</strong><span>{item.provider_code} · {item.service_level}</span></div>
            <dl><div><dt>Stage</dt><dd>{item.lifecycle_stage.replaceAll("_", " ")}</dd></div><div><dt>Status</dt><dd>{item.lifecycle_status}</dd></div><div><dt>SLA</dt><dd className={item.sla_breach_flag === "true" ? "red-text" : "green-text"}>{item.sla_breach_flag === "true" ? "Breached" : "Within"}</dd></div><div><dt>Evidence date</dt><dd>{item.metric_date}</dd></div></dl>
          </article>)}</div>}
          {shipmentState === "connected" && !entities.length && <DataState kind="empty" title="No matching shipments" message="No shipment entities match this provider and lane at the current cutoff." />}
          {nextToken && <button className="outline-button network-more" disabled={shipmentState === "loading"} onClick={() => void loadMore()}>Load next 25</button>}
        </article>
      </section>
      <p className="data-disclaimer">This internal view is bounded to operational actual-calendar evidence at or before {contract.as_of_date}. Costs, raw port identifiers, infrastructure identifiers, and future simulations are excluded.</p>
    </>}
  </div>;
}

function DemoShipments({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Shipments & inventory" copy="Connect network risks to the cargo and inventory they affect." />
    <section className="metric-grid compact"><Metric label="Active shipments" value="46" note="21 inbound FCL" /><Metric label="Delayed" value="11" note="4 over 48 hours" tone="amber" /><Metric label="At-risk FCL" value="15" note="Across 2 ports" tone="red" /><Metric label="Critical SKUs" value="6" note="Below 10 days cover" /></section>
    <div className="table-card shipment-table">
      <div className="shipment-row table-head"><span>Reference</span><span>Route</span><span>ETA</span><span>FCL</span><span>Inventory cover</span><span>Risk</span><span>Action</span></div>
      {shipments.map((item) => <button className="shipment-row" key={item.ref} onClick={() => go("brief")}>
        <strong>{item.ref}</strong><span>{item.route}</span><span>{item.eta}</span><span>{item.fcl}</span><span>{item.inventory}</span><span><b className={`risk-pill ${item.risk.toLowerCase()}`}>{item.risk}</b></span><span className="row-link">{item.action} →</span>
      </button>)}
    </div>
    <p className="data-disclaimer">Entity drill-down is available only inside the authenticated staging cockpit; this public workspace remains synthetic.</p>
  </div>;
}

function Outcomes({ outcomes, cohortSummary, operationsState, operationsMessage, refresh }: {
  outcomes: OperationsOutcome[];
  cohortSummary: OutcomeCohortSummary | null;
  operationsState: OperationsLoadState;
  operationsMessage: string;
  refresh: () => Promise<void>;
}) {
  const comparisonView = cohortSummary?.descriptive_comparison_view ?? null;
  const [fingerprintVerification, setFingerprintVerification] = useState<{
    view: typeof comparisonView;
    results: Record<string, OutcomeComparisonFingerprintVerification>;
    retry_attempts: Record<string, 1>;
  }>({ view: null, results: {}, retry_attempts: {} });
  useEffect(() => {
    if (comparisonView?.status !== "AVAILABLE") return;
    let current = true;
    void Promise.all(comparisonView.cohorts.map(async (cohort) => {
      const key = `${cohort.decision_brief_version}:${cohort.selected_alternative}:${cohort.integrity?.digest ?? "missing"}`;
      return [key, await verifyOutcomeComparisonFingerprint(cohort)] as const;
    })).then((results) => {
      if (current) setFingerprintVerification({
        view: comparisonView,
        results: Object.fromEntries(results),
        retry_attempts: {},
      });
    });
    return () => { current = false; };
  }, [comparisonView]);
  const retryFingerprintVerification = async (
    cohort: NonNullable<typeof comparisonView>["cohorts"][number],
    verificationKey: string,
  ) => {
    const existing = fingerprintVerification.view === comparisonView
      ? fingerprintVerification.results[verificationKey]
      : undefined;
    const attempts = fingerprintVerification.view === comparisonView
      ? fingerprintVerification.retry_attempts[verificationKey] ?? 0
      : 0;
    if (!existing || !isOutcomeComparisonFingerprintRetryable(existing) || attempts >= 1) return;
    setFingerprintVerification((current) => {
      if (current.view !== comparisonView) return current;
      const results = { ...current.results };
      delete results[verificationKey];
      return {
        view: current.view,
        results,
        retry_attempts: { ...current.retry_attempts, [verificationKey]: 1 },
      };
    });
    const result = await verifyOutcomeComparisonFingerprint(cohort);
    setFingerprintVerification((current) => current.view === comparisonView
      ? {
        view: current.view,
        results: { ...current.results, [verificationKey]: result },
        retry_attempts: current.retry_attempts,
      }
      : current);
  };
  if (operationsState === "demo") return <DemoOutcomes />;
  const pending = outcomes.filter((item) => item.evidence_status === "NOT_OBSERVED");
  const observed = outcomes.filter((item) => item.evidence_status === "OBSERVED_ACTUAL_CALENDAR");
  const successful = observed.filter((item) => ["SUCCESSFUL", "PARTIALLY_SUCCESSFUL"].includes(item.outcome_status));
  const averageEffect = observed.length
    ? `${(observed.reduce((total, item) => total + Number(item.effect_pct ?? 0), 0) / observed.length).toFixed(1)}%`
    : "—";
  return <div className="page">
    <PageTitle eyebrow="LEARN" title="Outcome review" copy="Compare completed Actions with cutoff-eligible evidence and trace each result to its immutable Decision Brief proposal." action={<button className="outline-button" onClick={() => void refresh()}>Refresh outcomes</button>} />
    <OperationsState state={operationsState} message={operationsMessage} label="Outcome Review" onRetry={refresh} />
    {operationsState === "connected" && <>
      <section className="metric-grid compact">
        <Metric label="Pending observation" value={String(pending.length)} note="Not counted as actual evidence" tone="amber" />
        <Metric label="Observed outcomes" value={String(observed.length)} note="Actual-calendar evidence only" />
        <Metric label="Successful outcomes" value={String(successful.length)} note={observed.length ? "Observed evidence" : "No mature evidence yet"} tone={successful.length ? "green" : ""} />
        <Metric label="Average observed effect" value={averageEffect} note={observed.length ? "Across mature outcomes" : "Pending outcomes excluded"} />
      </section>
      {!cohortSummary && <DataState kind="partial" title="Decision cohorts unavailable" message="This Operations API build does not expose the versioned Decision-contract cohort summary. Outcome rows remain available." />}
      {cohortSummary?.status === "NO_ELIGIBLE_BOUND_OUTCOMES" && <DataState kind="partial" title="No eligible Decision cohorts" message="No observed, cutoff-eligible synthetic Outcomes have a complete Decision Brief binding. Pending and unbound records are excluded." />}
      {cohortSummary?.evidence_sufficiency_gate.configuration_status === "PENDING_HUMAN_APPROVAL" && <DataState kind="partial" title="Comparison thresholds await human approval" message="No minimum sample or result-coverage threshold has been approved. Cohort statistics remain descriptive and comparison eligibility is blocked." />}
      {cohortSummary?.status === "AVAILABLE" && <section className="card outcome-cohort-summary">
        <CardHead title="Decision-contract Outcome cohorts" copy="Descriptive synthetic evidence grouped by immutable Decision Brief version and selected alternative." />
        {cohortSummary.evidence_sufficiency_gate.configuration_status === "HUMAN_APPROVED_CONTRACT" && <div className="cohort-threshold-contract">
          <strong>Human-approved descriptive gate</strong>
          <span>At least {cohortSummary.evidence_sufficiency_gate.thresholds.minimum_observed_outcomes} observed Outcomes and {cohortSummary.evidence_sufficiency_gate.thresholds.minimum_distinct_result_states} represented result states per cohort.</span>
          <small>{cohortSummary.evidence_sufficiency_gate.threshold_contract_version}</small>
        </div>}
        <div className="outcome-cohort-grid">{cohortSummary.cohorts.map((cohort) => <article key={`${cohort.decision_brief_version}:${cohort.selected_alternative}`}>
          <small>{cohort.decision_brief_version}</small>
          <strong>{cohort.selected_alternative.replaceAll("_", " ")}</strong>
          <span>{cohort.observed_outcome_count} observed synthetic Outcome{cohort.observed_outcome_count === 1 ? "" : "s"}</span>
          <b className={`cohort-sufficiency ${cohort.evidence_sufficiency.comparison_eligible ? "eligible" : "blocked"}`}>{cohort.evidence_sufficiency.status.replaceAll("_", " ")}</b>
          <dl>
            <div><dt>Successful / partial</dt><dd>{cohort.status_counts.successful} / {cohort.status_counts.partially_successful}</dd></div>
            <div><dt>Failed / inconclusive</dt><dd>{cohort.status_counts.failed} / {cohort.status_counts.inconclusive}</dd></div>
            <div><dt>Effect range</dt><dd>{cohort.effect_pct.minimum}% to {cohort.effect_pct.maximum}%</dd></div>
            <div><dt>Average effect</dt><dd>{cohort.effect_pct.average}%</dd></div>
            <div><dt>Result-state coverage</dt><dd>{cohort.evidence_sufficiency.distinct_result_states} of 4 states</dd></div>
            <div><dt>Outcome evidence gap</dt><dd>{cohort.evidence_gap.additional_observed_outcomes === null ? "Pending contract" : cohort.evidence_gap.additional_observed_outcomes === 0 ? "Target met" : `${cohort.evidence_gap.additional_observed_outcomes} additional`}</dd></div>
            <div><dt>Result-state gap</dt><dd>{cohort.evidence_gap.additional_distinct_result_states === null ? "Pending contract" : cohort.evidence_gap.additional_distinct_result_states === 0 ? "Target met" : `${cohort.evidence_gap.additional_distinct_result_states} additional`}</dd></div>
            <div><dt>Comparison eligible</dt><dd>{cohort.evidence_sufficiency.comparison_eligible ? "Yes — descriptive only" : "No"}</dd></div>
          </dl>
        </article>)}</div>
        <p className="data-disclaimer">Evidence gaps are arithmetic differences from the approved 20/2 contract, not instructions to create Outcomes or advance the lifecycle. Observed means the synthetic result matured under the actual-calendar cutoff. These cohorts are descriptive only—not causal estimates, realised value, model readiness, or policy authority.</p>
      </section>}
      {cohortSummary?.status === "AVAILABLE" && !comparisonView && <DataState kind="partial" title="Cohort comparison contract unavailable" message="This Operations API build does not expose the versioned eligible-cohort comparison view. Individual cohort evidence remains available." />}
      {cohortSummary?.status === "AVAILABLE" && comparisonView?.status === "INSUFFICIENT_ELIGIBLE_COHORTS" && <DataState kind="partial" title="Cohort comparison unavailable" message={`${comparisonView.eligible_cohort_count} of ${comparisonView.required_eligible_cohort_count} required cohorts pass the approved gate. Evidence gaps above explain what is missing; no data collection is recommended.`} />}
      {comparisonView?.status === "AVAILABLE" && <section className="card cohort-comparison-view">
        <CardHead title="Eligible Outcome cohort comparison" copy="Side-by-side descriptive status mix and effect ranges for cohorts that independently pass the approved 20/2 gate." />
        <div className="cohort-comparison-grid">{comparisonView.cohorts.map((cohort) => {
          const verificationKey = `${cohort.decision_brief_version}:${cohort.selected_alternative}:${cohort.integrity?.digest ?? "missing"}`;
          const verification = fingerprintVerification.view === comparisonView
            ? fingerprintVerification.results[verificationKey]
            : undefined;
          const retryable = verification
            ? isOutcomeComparisonFingerprintRetryable(verification)
              && (fingerprintVerification.retry_attempts[verificationKey] ?? 0) < 1
            : false;
          if (verification?.status !== "VERIFIED" || !cohort.integrity) return <article className="comparison-integrity-blocked" key={verificationKey}>
            <small>Comparison integrity</small>
            <strong>{verification?.status === "MISMATCH" ? "Verification failed" : "Verifying fingerprint"}</strong>
            {verification?.status === "MISMATCH" && <b className="comparison-diagnostic-code">{verification.reason_code}</b>}
            <span>{verification?.status === "MISMATCH"
              ? `${comparisonFingerprintDiagnostic[verification.reason_code]} Comparison metrics and provenance are withheld. ${retryable ? "You may retry this browser-only check without requesting new data." : "Refresh the Outcome review before relying on this cohort."}`
              : "Comparison metrics and provenance remain hidden until browser verification completes."}</span>
            {retryable && <button className="comparison-local-retry" type="button" onClick={() => void retryFingerprintVerification(cohort, verificationKey)}>Retry local verification</button>}
          </article>;
          return <article className="comparison-integrity-verified" key={verificationKey}>
          <small>{cohort.decision_brief_version}</small>
          <strong>{cohort.selected_alternative.replaceAll("_", " ")}</strong>
          <span>{cohort.observed_outcome_count} observed synthetic Outcomes</span>
          <b className="comparison-integrity-status">Fingerprint verified</b>
          <dl>
            <div><dt>Successful</dt><dd>{cohort.status_percentages.successful}%</dd></div>
            <div><dt>Partially successful</dt><dd>{cohort.status_percentages.partially_successful}%</dd></div>
            <div><dt>Failed</dt><dd>{cohort.status_percentages.failed}%</dd></div>
            <div><dt>Inconclusive</dt><dd>{cohort.status_percentages.inconclusive}%</dd></div>
            <div><dt>Average effect</dt><dd>{cohort.effect_pct.average}%</dd></div>
            <div><dt>Effect range</dt><dd>{cohort.effect_pct.minimum}% to {cohort.effect_pct.maximum}%</dd></div>
          </dl>
          <details className="comparison-provenance">
            <summary>View comparison provenance</summary>
            <dl>
              <div><dt>Binding source</dt><dd>{cohort.provenance.decision_binding.binding_source.replaceAll("_", " ")}</dd></div>
              <div><dt>Sydney cutoff</dt><dd>{cohort.provenance.evidence_contract.as_of_date}</dd></div>
              <div><dt>Evidence basis</dt><dd>{cohort.provenance.evidence_contract.execution_mode} / {cohort.provenance.evidence_contract.time_basis}</dd></div>
              <div><dt>Threshold contract</dt><dd>{cohort.provenance.evidence_contract.threshold_contract_version}</dd></div>
              <div><dt>Aggregation contract</dt><dd>{cohort.provenance.evidence_contract.cohort_summary_schema_version}</dd></div>
              <div><dt>Identifiers</dt><dd>Aggregate only—none exposed</dd></div>
              <div><dt>Integrity algorithm</dt><dd>{cohort.integrity.algorithm}</dd></div>
              <div><dt>Verification scope</dt><dd>{cohort.integrity.verification_scope.replaceAll("_", " ")}</dd></div>
            </dl>
            <code className="comparison-fingerprint">{cohort.integrity.digest}</code>
            <p>Deterministic content fingerprint only—not a digital signature, source-authenticity attestation, or business-validity proof.</p>
          </details>
        </article>})}</div>
        <p className="data-disclaimer">This view produces no ranking, preferred alternative, causal superiority, statistical significance, or Action recommendation. It compares descriptive synthetic distributions only.</p>
      </section>}
      <div className="decision-list">{outcomes.map((item) => <article className="decision-card" key={item.outcome_id}>
        <div className={`decision-priority ${(item.alert_severity ?? "medium").toLowerCase()}`}><i /><span>{item.outcome_status}</span></div>
        <div className="outcome-decision-main">
          <div className="decision-main"><small>{item.outcome_id}</small><strong>{(item.action_type ?? "Completed Action").replaceAll("_", " ")}</strong><span>Shipment {item.shipment_id} · Action {item.action_id}</span></div>
          <span className="decision-source">{item.decision_brief_version && item.selected_alternative ? `Decision source: ${item.decision_brief_version} · ${item.selected_alternative.replaceAll("_", " ")}` : "Decision source unavailable — legacy or unbound Action"}</span>
        </div>
        <div className="decision-value"><small>{item.evidence_status === "NOT_OBSERVED" ? "Evidence" : "Observed effect"}</small><strong>{item.evidence_status === "NOT_OBSERVED" ? "Not observed" : `${item.effect_pct}%`}</strong></div>
        <div className="decision-due"><small>{item.evidence_status === "NOT_OBSERVED" ? "Observation due" : "Observed"}</small><strong>{item.evidence_status === "NOT_OBSERVED" ? item.observation_due_date : item.observed_date}</strong></div>
        <span className="status-button">{item.evidence_status === "NOT_OBSERVED" ? "Pending" : "Actual calendar"}</span>
      </article>)}</div>
      <p className="data-disclaimer">Decision provenance identifies the immutable proposal contract only. Simulated Outcome effects are not causal estimates or real logistics performance.</p>
      {outcomes.length === 0 && <DataState kind="empty" title="No operational Outcomes" message="No operational Outcomes are available at the current Sydney cutoff." />}
    </>}
  </div>;
}

function LearningReview({ contract, state, message, refresh }: {
  contract: LearningEvidence | null;
  state: OperationsLoadState;
  message: string;
  refresh: () => Promise<void>;
}) {
  return <div className="page">
    <PageTitle eyebrow="LEARN" title="Learning Review" copy="See whether cutoff-eligible Outcomes support a review-only policy proposal without activating or replacing deterministic rules." action={<button className="outline-button" onClick={() => void refresh()}>Refresh learning evidence</button>} />
    <OperationsState state={state} message={message} label="Learning Review" onRetry={refresh} />
    {state === "connected" && contract && <>
      <section className="metric-grid compact">
        <Metric label="Eligible Outcomes" value={String(contract.gate.eligible_observed_outcomes)} note={`Minimum ${contract.gate.minimum_observed_outcomes}`} />
        <Metric label="Remaining to gate" value={String(contract.gate.remaining_outcomes)} note={contract.gate.gate_met ? "Evidence gate met" : "Learning remains blocked"} tone={contract.gate.gate_met ? "green" : "amber"} />
        <Metric label="Synthetic success rate" value={contract.outcome_summary.success_rate_pct === null ? "—" : `${contract.outcome_summary.success_rate_pct}%`} note="Successful + partially successful" />
        <Metric label="Proposal state" value={contract.proposal?.status.replaceAll("_", " ") ?? "Not created"} note="Human review is always required" />
      </section>
      {!contract.gate.gate_met && <DataState kind="partial" title="Learning evidence is not yet eligible" message={`${contract.gate.remaining_outcomes} more observed actual-calendar Outcomes are required. Pending Outcomes and future simulations do not count.`} />}
      {contract.gate.gate_met && !contract.proposal && <DataState kind="idle" title="Evidence gate met; proposal not recorded" message="The lifecycle generator has not yet recorded a governed policy proposal for this cutoff. No policy has changed." />}
      {contract.proposal && <article className="card learning-proposal">
        <CardHead title="Review-only policy proposal" copy={contract.proposal.proposed_change.replaceAll("_", " ")} />
        <dl>
          <div><dt>Status</dt><dd>{contract.proposal.status.replaceAll("_", " ")}</dd></div>
          <div><dt>Source policy</dt><dd>{contract.proposal.source_policy_version}</dd></div>
          <div><dt>Observed Outcomes</dt><dd>{contract.proposal.observed_outcome_count}</dd></div>
          <div><dt>Rollback target</dt><dd>{contract.proposal.rollback_policy_version}</dd></div>
        </dl>
      </article>}
      <p className="data-disclaimer">Sydney cutoff {contract.as_of_date}. This gate is synthetic policy-review evidence only; it is not model or production readiness. Policy activation always requires a separate named-human approval. These simulated Outcomes are never real logistics performance, and deterministic safety rules remain in force.</p>
    </>}
  </div>;
}

function LabelReadiness({ contract, state, message, refresh }: {
  contract: ProviderLabelReadiness | null;
  state: OperationsLoadState;
  message: string;
  refresh: () => Promise<void>;
}) {
  if (state === "demo") return <div className="page">
    <PageTitle eyebrow="EVALUATE" title="Provider Label Readiness" copy="Governed provider-level label evidence is available only inside the authenticated staging cockpit." />
    <p className="data-disclaimer">The public demonstration cannot claim label maturity, model readiness, or training authority.</p>
  </div>;
  const readable = (value: string) => value.replaceAll("_", " ").toLowerCase();
  return <div className="page">
    <PageTitle eyebrow="EVALUATE" title="Provider Label Readiness" copy="See exactly which observed actual-calendar labels are eligible for supervised evaluation and why each provider remains blocked." action={<button className="outline-button" onClick={() => void refresh()}>Refresh readiness</button>} />
    <OperationsState state={state} message={message} label="Provider Label Readiness" onRetry={refresh} />
    {state === "connected" && contract && <>
      {contract.status !== "ready" && <DataState kind="partial" title="Supervised evaluation remains blocked" message={`${contract.coverage.ready_provider_groups} of ${contract.coverage.provider_groups} provider groups meet every target gate. Pending labels and future simulations never count.`} />}
      {contract.groups.length === 0 && <DataState kind="empty" title="No eligible provider cohorts" message={`No operational actual-calendar label cohorts are available at the ${contract.as_of_date} Sydney cutoff.`} />}
      <section className="metric-grid compact">
        <Metric label="Provider groups ready" value={`${contract.coverage.ready_provider_groups}/${contract.coverage.provider_groups}`} note="Every target must pass independently" tone={contract.status === "ready" ? "green" : "amber"} />
        <Metric label="Eligible targets" value={`${contract.coverage.eligible_targets}/${contract.coverage.total_targets}`} note="Evaluation gate only" />
        <Metric label="Observed labels" value={String(contract.coverage.observed_labels)} note={`Minimum ${contract.thresholds.minimum_observed_per_provider} per provider`} />
        <Metric label="Pending labels" value={String(contract.coverage.pending_labels)} note="Excluded from all targets" tone="amber" />
      </section>
      <section className="label-readiness-grid">
        {contract.groups.map((group) => {
          const targets = [
            { name: "SLA breach", target: group.targets.sla_breach },
            { name: "Delay risk", target: group.targets.delay_risk },
            { name: "Cost variance", target: group.targets.cost_variance },
          ];
          return <article className={`card label-readiness-card ${group.status}`} key={`${group.transport_mode}-${group.provider_code}`}>
            <header><div><small>{group.transport_mode}</small><strong>{group.provider_code}</strong><span>Latest eligible label date {group.source_latest_date}</span></div><b>{readable(group.status)}</b></header>
            <dl className="label-coverage">
              <div><dt>Observed</dt><dd>{group.observed_label_count}</dd></div>
              <div><dt>Pending</dt><dd>{group.pending_label_count}</dd></div>
              <div><dt>Observed rate</dt><dd>{group.observed_rate_pct === null ? "Unavailable" : `${group.observed_rate_pct}%`}</dd></div>
            </dl>
            <div className="label-targets">{targets.map(({ name, target }) => <section key={name}>
              <div><strong>{name}</strong><b className={target.evaluation_eligible ? "ready" : "blocked"}>{target.evaluation_eligible ? "Evaluation eligible" : "Blocked"}</b></div>
              {"positive_count" in target
                ? <p>{target.positive_count} positive / {target.negative_count} negative · gaps: {target.remaining_observed} observed, {target.remaining_positive} positive, {target.remaining_negative} negative</p>
                : <p>{target.label_count} labels / {target.distinct_value_count} distinct values · gaps: {target.remaining_observed} observed, {target.remaining_distinct_values} distinct</p>}
              {target.blockers.length > 0 && <small>{target.blockers.map(readable).join(" · ")}</small>}
            </section>)}</div>
          </article>;
        })}
      </section>
      <p className="data-disclaimer">Sydney cutoff {contract.as_of_date}. This aggregate contains no shipment, Action, or Outcome identifiers. It excludes pending labels and future simulations. Passing a threshold permits governed evaluation only; model training, model promotion, deployment, recurring prediction, and production readiness remain unauthorized.</p>
    </>}
  </div>;
}

function DemoOutcomes() {
  return <div className="page" data-claim-id="next-outcomes-summary" data-claim-classification="ILLUSTRATIVE">
    <PageTitle eyebrow="LEARN" title="Illustrative outcomes & value" copy="Explore how outcome and value reporting could work. No execution or realised-value evidence is shown." action={<span className="outline-button static-control">Fixed scenario</span>} />
    <section className="metric-grid"><Metric label="Illustrative decisions" value="24" note="Assumed 89% acceptance" /><Metric label="Modelled scenario value" value="$128.4k" note="Illustrative comparison only" tone="green" /><Metric label="Illustrative storage avoidance" value="$46.2k" note="12 scenario interventions" /><Metric label="Illustrative stockout scenarios" value="7" note="Across 18 synthetic SKUs" /><Metric label="Illustrative forecast score" value="84%" note="Not operational accuracy" /></section>
    <section className="outcome-grid">
      <article className="card outcome-chart"><CardHead title="Illustrative cumulative scenario value" copy="Fixed modelled examples, not realised benefit" /><div className="line-chart"><div className="chart-line" /><span className="chart-label l1">$0</span><span className="chart-label l2">$50k</span><span className="chart-label l3">$100k</span><div className="chart-dot" /></div><div className="chart-months"><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span></div></article>
      <article className="card"><CardHead title="Illustrative scenario outcomes" copy="Expected impact compared with assumed scenario result" /><div className="outcome-list">
        <div><i className="success">✓</i><span><strong>Early container collection · Botany</strong><small>Modelled storage avoidance · 18 Jul</small></span><b>$9,240</b></div>
        <div><i className="success">✓</i><span><strong>Expedited replenishment · Brisbane</strong><small>Illustrative stockout avoidance · 14 Jul</small></span><b>$21,800</b></div>
        <div><i className="neutral">—</i><span><strong>Held spot-rate booking · Shanghai</strong><small>Rate unchanged · 11 Jul</small></span><b>$0</b></div>
      </div></article>
    </section>
    <p className="data-disclaimer">All values shown in this demonstration workspace are fixed synthetic examples. They are not Action execution, observed Outcome, realised business value, or operational forecast evidence.</p>
  </div>;
}

function DecisionBrief({ diverted, setDiverted, decision, setDecision, economics, contract, selectedReviewActionId, openSelectedAction, go }: {
  diverted: number; setDiverted: (n: number) => void; decision: string;
  setDecision: (v: "pending" | "approved" | "rejected") => void;
  economics: { noAction: number; avoided: number; reroute: number; net: number; stockout: string };
  contract: DecisionBriefV1 | null;
  selectedReviewActionId: string | null;
  openSelectedAction: () => void;
  go: (view: View) => void;
}) {
  if (internalOperationsEnabled() && contract) {
    return <OperationalDecisionBrief contract={contract} selectedActionReview={Boolean(selectedReviewActionId)} openSelectedAction={openSelectedAction} go={go} />;
  }
  return <div className="page brief-page" data-claim-id="next-decision-brief" data-claim-classification="ILLUSTRATIVE">
    <button className="back-link" onClick={() => go("decisions")}>← Back to decision queue</button>
    <div className="brief-title">
      <div><span className="critical-label">CRITICAL</span><small>DEC-PORT-0001 · Updated 09:30 AEST</small><h1>Protect critical inventory before Sydney port disruption compounds.</h1><p>Congestion is 2.5× baseline and strike probability has reached 82%. Twelve inbound FCL may exceed free storage before inventory cover runs out.</p></div>
      <div className={`decision-status ${decision}`}><span>Decision status</span><strong>{decision === "pending" ? "Pending review" : decision}</strong><small>Owner · Mia Chen</small></div>
    </div>
    <section className="metric-grid compact brief-metrics"><Metric label="Composite risk" value="HIGH" note="Congestion + strike" tone="red" /><Metric label="FCL exposed" value="12" note="Critical SKU cargo" /><Metric label="Cost exposure" value={money(economics.noAction)} note="Without action" /><Metric label="Inventory cover" value="8 days" note="vs 9-day dwell" /></section>
    <section className="brief-grid">
      <article className="card"><CardHead title="Why the risk escalated" copy="Signals crossed intervention thresholds" /><div className="signal-meter"><span>Port congestion index <b>0.87</b></span><div><i style={{width:"87%"}} /></div><small>Baseline 0.35</small></div><div className="signal-meter amber"><span>Labour-strike probability <b>82%</b></span><div><i style={{width:"82%"}} /></div><small>Escalation threshold 60%</small></div><div className="cover-compare"><div><span>Inventory cover</span><strong>8 days</strong></div><b>1-day gap</b><div><span>Expected dwell</span><strong>9 days</strong></div></div></article>
      <article className="card"><CardHead title="Recommended action" copy="Assumed scenario confidence · 80%" /><div className="recommendation"><i>↗</i><div><strong>Divert {diverted} high-priority FCL to Melbourne</strong><p>Move cargo to Sydney DC by rail or truck. Keep {12-diverted} lower-priority FCL on the original route and review daily.</p></div></div><div className="route-flow"><div><i className="red" /><strong>Sydney</strong><span>Disrupted</span></div><b>→ <small>{diverted} FCL</small></b><div><i className="blue" /><strong>Melbourne</strong><span>Alternate</span></div><b>→ <small>Rail</small></b><div><i className="green" /><strong>Sydney DC</strong><span>Protected</span></div></div></article>
      <article className="card"><CardHead title="Decision economics" copy="Scenario changes with diversion volume" /><div className="economics-list"><div><span>No-action exposure</span><strong>{money(economics.noAction)}</strong></div><div><span>Avoided storage</span><strong className="green-text">+{money(economics.avoided)}</strong></div><div><span>Reroute cost</span><strong className="amber-text">−{money(economics.reroute)}</strong></div></div><div className="net-benefit"><span>Net modelled benefit</span><strong>{money(economics.net)}</strong><small>Stockout risk after action · <b>{economics.stockout}</b></small></div></article>
      <article className="card review-card"><CardHead title="Operator review" copy="Human approval required before execution" /><label className="range-label"><span>FCL to divert <strong>{diverted}</strong></span><input aria-label="FCL to divert" type="range" min="0" max="12" value={diverted} onChange={(e) => {setDiverted(Number(e.target.value)); setDecision("pending");}} /><small><span>0</span><span>Recommended · 8</span><span>12</span></small></label><label className="select-label"><span>Decision owner</span><select><option>Mia Chen · Import Operations</option><option>James Wu · Inventory Planning</option><option>Sarah Lim · Control Tower</option></select></label><div className="rationale"><span>Decision rationale</span><p>Expected dwell exceeds inventory cover and free-storage time. Selective diversion protects critical inventory while limiting unnecessary reroute cost.</p></div><div className="decision-buttons"><button onClick={() => setDecision("rejected")}>Reject</button><button onClick={() => setDecision("approved")}>Approve diversion</button></div><small className="demo-note">Demonstration only · no instruction is sent to a carrier or terminal.</small></article>
    </section>
  </div>;
}

function OperationalDecisionBrief({ contract, selectedActionReview, openSelectedAction, go }: {
  contract: DecisionBriefV1;
  selectedActionReview: boolean;
  openSelectedAction: () => void;
  go: (view: View) => void;
}) {
  const readable = (value: string) => value.replaceAll("_", " ");
  const isCost = contract.decision_type === "COST_ANOMALY";
  const riskScope = isCost ? contract.risk.cost_scope : contract.risk.milestone;
  const exposureValue = isCost ? contract.exposure.variance_pct : contract.exposure.delay_hours;
  const thresholdValue = isCost ? contract.exposure.threshold_pct : contract.exposure.threshold_hours;
  const breachMargin = isCost ? contract.exposure.breach_margin_pct : contract.exposure.breach_margin_hours;
  const exposureUnit = isCost ? "%" : "h";
  const exposureLabel = isCost ? "Cost variance" : "Delay exposure";
  const sourceDetail = isCost
    ? `${contract.source.source_contract_version} · Rate-card version unavailable in Alert contract`
    : contract.source.evidence_class;
  return <div className="page brief-page">
    <button className="back-link" onClick={() => go(selectedActionReview ? "decisions" : "signals")}>← {selectedActionReview ? "Back to decision queue" : "Back to risk hotspots"}</button>
    <div className="brief-title">
      <div><span className="critical-label">{contract.decision_type}</span><small>DECISION BRIEF V1 · Sydney cutoff {contract.as_of_date}</small><h1>{isCost ? "Review the governed response to a cost anomaly." : "Review the governed response to an SLA breach."}</h1><p>This brief is derived from one operational-calendar synthetic Alert. It recommends a bounded review action; it does not claim execution, an observed Outcome, or financial value.</p></div>
      <div className="decision-status pending"><span>Review status</span><strong>Human review required</strong><small>{readable(contract.urgency.status)}</small></div>
    </div>
    <section className="metric-grid compact brief-metrics">
      <Metric label="Risk" value={contract.risk.severity} note={readable(riskScope)} tone="red" />
      <Metric label={exposureLabel} value={`${exposureValue} ${exposureUnit}`} note={readable(contract.exposure.metric_name)} />
      <Metric label="Above threshold" value={`${breachMargin} ${exposureUnit}`} note="Derived exposure" />
      <Metric label="Expected benefit" value="NOT ESTIMATED" note="No intervention-effect model" />
    </section>
    <section className="brief-grid">
      <article className="card"><CardHead title="Why review is required" copy="Observed input and derived exposure stay separate" /><div className="economics-list"><div><span>{isCost ? "Observed variance input" : "Observed delay input"}</span><strong>{exposureValue} {isCost ? "percent" : "hours"}</strong></div><div><span>Governed threshold</span><strong>{thresholdValue} {isCost ? "percent" : "hours"}</strong></div><div><span>Derived breach margin</span><strong>{breachMargin} {isCost ? "percentage points" : "hours"}</strong></div></div><p className="data-disclaimer">Risk evidence: {contract.risk.evidence_class} · exposure evidence: {contract.exposure.evidence_class}</p>{isCost && <p className="data-disclaimer">Cost source: {sourceDetail}. No rate-card identifier is inferred.</p>}</article>
      <article className="card"><CardHead title="Recommended action" copy={`Deterministic ${contract.decision_type} rule`} /><div className="recommendation"><i>↗</i><div><strong>{readable(contract.recommendation.action_type)}</strong><p>{contract.recommendation.rationale}</p></div></div><p className="data-disclaimer">This recommendation requires human review and does not authorize execution.</p></article>
      <article className="card"><CardHead title="Bounded alternatives" copy="Including an explicit no-action path" /><div className="economics-list">{contract.alternatives.map((alternative) => <div key={alternative.action_type}><span>{alternative.label}</span><strong>{alternative.recommended ? "RECOMMENDED" : "AVAILABLE"}</strong></div>)}</div></article>
      <article className="card review-card"><CardHead title="Benefit and authority" copy="No pseudo-precision" /><div className="economics-list"><div><span>Benefit estimate</span><strong>{readable(contract.benefit_estimate.status)}</strong></div><div><span>Assumption set</span><strong>{contract.benefit_estimate.assumption_set_version ?? "NONE"}</strong></div><div><span>Monetary exposure</span><strong>NOT ESTIMATED</strong></div></div><button className="primary-button" onClick={selectedActionReview ? openSelectedAction : () => go("actions")}>{selectedActionReview ? "Open selected Action" : "Open governed Action Board"}</button><p className="data-disclaimer">{selectedActionReview ? "This returns only to the Action whose immutable binding matches this Brief. " : ""}The Action Board retains signed-human role checks and append-only audit semantics. This brief itself performs no mutation.</p></article>
    </section>
    <p className="data-disclaimer">Source: {sourceDetail} · execution authorized: no · Outcome observed: no · financial value estimated: no.</p>
  </div>;
}

function Metric({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) {
  return <article className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>;
}

function CardHead({ title, copy, action }: { title: string; copy: string; action?: React.ReactNode }) {
  return <div className="card-head"><div><h2>{title}</h2><p>{copy}</p></div>{action}</div>;
}

function Port({ x, y, name, level }: { x: string; y: string; name: string; level: string }) {
  return <div className={`port ${level}`} style={{left:x,top:y}}><i /><span>{name}</span></div>;
}
