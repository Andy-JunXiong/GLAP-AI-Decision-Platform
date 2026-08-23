"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActionEvidence,
  ActionOperation,
  OperationsAction,
  OperationsOutcome,
  PipelineHealth as PipelineHealthData,
  ForecastContract,
  LearningEvidence,
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
  loadNetworkSummary,
  loadRiskHotspots,
  loadShipmentDrilldown,
  mutateAction,
  readOperationsToken,
} from "./operations-api";
import {
  finishOperationsSignIn,
  internalAuthenticationEnabled,
  operationsSignedIn,
  signInOperations,
  signOutOperations,
} from "./operations-auth";
import "./operations.css";

type View = "overview" | "signals" | "decisions" | "actions" | "shipments" | "outcomes" | "learning" | "forecasts" | "health" | "brief";
type OperationsLoadState = "demo" | "loading" | "connected" | "auth_required" | "error";
type ShipmentLoadState = "idle" | "loading" | "connected" | "partial" | "error";
type DataStateKind = "loading" | "empty" | "stale" | "partial" | "failed" | "auth_required" | "idle";

const navItems: { id: View; label: string; icon: string; internalOnly?: boolean }[] = [
  { id: "overview", label: "Control Tower", icon: "⌂" },
  { id: "signals", label: "Signals", icon: "⌁" },
  { id: "decisions", label: "Decisions", icon: "◇" },
  { id: "shipments", label: "Shipments", icon: "▣" },
  { id: "outcomes", label: "Outcomes", icon: "↗" },
  { id: "actions", label: "Action Board", icon: "A" },
  { id: "learning", label: "Learning Review", icon: "L", internalOnly: true },
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
  const [operationsActions, setOperationsActions] = useState<OperationsAction[]>([]);
  const [operationsRisks, setOperationsRisks] = useState<OperationsRisk[]>([]);
  const [operationsOutcomes, setOperationsOutcomes] = useState<OperationsOutcome[]>([]);
  const [pipelineHealth, setPipelineHealth] = useState<PipelineHealthData | null>(null);
  const [forecastContract, setForecastContract] = useState<ForecastContract | null>(null);
  const [learningContract, setLearningContract] = useState<LearningEvidence | null>(null);
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
          return Promise.all([refreshOperations(), refreshPipelineHealth(), refreshForecasts(), refreshLearning(), refreshNetwork()]);
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
          setNetworkState("error");
          setNetworkMessage(signInMessage);
        });
    }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [refreshOperations, refreshPipelineHealth, refreshForecasts, refreshLearning, refreshNetwork]);

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
    setView(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="product-shell">
      <aside className="sidebar">
        <button className="logo" onClick={() => go("overview")} aria-label="GLAP home">
          <span>G</span><div><strong>GLAP</strong><small>Decision Intelligence</small></div>
        </button>
        <nav aria-label="Product navigation">
          <p>Workspace</p>
          {navItems.filter((item) => !item.internalOnly || internalOperationsEnabled()).map((item) => (
            <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => go(item.id)}>
              <i>{item.icon}</i>{item.label}
              {item.id === "decisions" && <b>3</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="system-state"><i /><div><strong>Monitoring active</strong><span>16 sources connected</span></div></div>
          <button className="user-card"><span>MC</span><div><strong>Mia Chen</strong><small>Import Operations</small></div><i>···</i></button>
        </div>
      </aside>

      <main className="app-main">
        <header className="app-header">
          <div className="mobile-brand"><strong>GLAP</strong></div>
          <div className="header-context">
            <span>Australia Operations</span><b>/</b><strong>{view === "brief" ? "Decision Brief" : navItems.find((item) => item.id === view)?.label}</strong>
          </div>
          <div className="header-actions">
            <span className="demo-badge">{internalOperationsEnabled() ? "Internal staging" : "Synthetic workspace"}</span>
            {internalOperationsEnabled() && internalAuthenticationEnabled() && (
              signedIn
                ? <button className="auth-button" onClick={signOutOperations}>Sign out</button>
                : <button className="auth-button" onClick={() => { void signInOperations(); }}>Internal sign in</button>
            )}
            <button aria-label="Notifications" className="notification">●<b>3</b></button>
            <button className="help">?</button>
          </div>
        </header>

        {view === "overview" && <Overview go={go} />}
        {view === "signals" && <Signals filter={signalFilter} setFilter={setSignalFilter} go={go} risks={operationsRisks} operationsState={operationsState} operationsMessage={operationsMessage} refresh={refreshOperations} />}
        {view === "decisions" && <Decisions go={go} actions={operationsActions} operationsState={operationsState} operationsMessage={operationsMessage} refresh={refreshOperations} />}
        {view === "actions" && <ActionBoard actions={operationsActions} operationsState={operationsState} operationsMessage={operationsMessage} submitOperation={submitOperation} refresh={refreshOperations} />}
        {view === "shipments" && <Shipments
          go={go} contract={networkContract} entities={shipmentEntities}
          state={networkState} message={networkMessage} shipmentState={shipmentState}
          selection={shipmentSelection} nextToken={shipmentNextToken}
          refresh={refreshNetwork} openGroup={openShipmentGroup} loadMore={loadMoreShipments}
        />}
        {view === "outcomes" && <Outcomes outcomes={operationsOutcomes} operationsState={operationsState} operationsMessage={operationsMessage} refresh={refreshOperations} />}
        {view === "learning" && <LearningReview contract={learningContract} state={learningState} message={learningMessage} refresh={refreshLearning} />}
        {view === "health" && <PipelineHealth health={pipelineHealth} state={healthState} message={healthMessage} refresh={refreshPipelineHealth} />}
        {view === "forecasts" && <ForecastAccuracy contract={forecastContract} state={forecastState} message={forecastMessage} refresh={refreshForecasts} />}
        {view === "brief" && (
          <DecisionBrief
            diverted={diverted}
            setDiverted={setDiverted}
            decision={decision}
            setDecision={setDecision}
            economics={economics}
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

function Overview({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="Thursday, 23 July · 09:42 AEST" title="Good morning, Mia." copy="Here is what needs attention across your logistics network." action={<button className="outline-button">Last 24 hours⌄</button>} />
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
        <button className="attention-item critical-item" onClick={() => go("brief")}>
          <span className="severity">CRITICAL</span><small>Due in 2h 14m</small>
          <strong>Divert 8 FCL via Melbourne</strong>
          <p>Sydney congestion and strike risk threaten critical inventory.</p>
          <div><span>12 FCL exposed</span><b>Protect $5,760 →</b></div>
        </button>
        <button className="attention-item">
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
      <article className="card value-card">
        <CardHead title="Value delivered" copy="Modelled benefit from executed decisions" action={<button onClick={() => go("outcomes")}>View outcomes →</button>} />
        <div className="value-hero"><span>Month to date</span><strong>$128,400</strong><small>estimated cost and loss avoided</small></div>
        <div className="value-list"><span><i />Storage & demurrage <b>$46.2k</b></span><span><i />Stockout avoidance <b>$61.8k</b></span><span><i />Freight optimisation <b>$20.4k</b></span></div>
      </article>
    </section>
  </div>;
}

function Signals({ filter, setFilter, go, risks, operationsState, operationsMessage, refresh }: {
  filter: string;
  setFilter: (v: string) => void;
  go: (view: View) => void;
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
      {visibleRisks.map((risk) => <button className="data-row" key={risk.alert_fingerprint} onClick={() => go("decisions")}>
        <span><b className={`risk-pill ${risk.severity.toLowerCase()}`}>{risk.severity}</b></span>
        <span><strong>{risk.alert_type.replaceAll("_", " ")}</strong><small>{risk.alert_grain} · {risk.alert_dimension}</small></span>
        <span><strong>{risk.metric_value}</strong><small>Threshold {risk.threshold_value}</small></span>
        <span>Shipment {risk.shipment_id}</span><span>{risk.last_detected_date}</span><span className="row-link">→</span>
      </button>)}
      {visibleRisks.length === 0 && <DataState kind="empty" title="No matching risk hotspots" message="No open operational Risks match this filter. Change the severity filter or refresh the latest evidence." />}
    </div>}
  </div>;
  return <div className="page">
    <PageTitle eyebrow="DETECT" title="Signal monitoring" copy="See emerging risks before they become operational disruption." action={<button className="primary-button">＋ Add source</button>} />
    <div className="toolbar"><div className="filters">{["All","Critical","High","Medium"].map((f) => <button className={filter === f ? "active" : ""} onClick={() => setFilter(f)} key={f}>{f}{f === "All" && " 4"}</button>)}</div><label className="search">⌕<input placeholder="Search signals" /></label></div>
    <div className="table-card">
      <div className="data-row table-head"><span>Risk</span><span>Signal</span><span>Current reading</span><span>Exposure</span><span>Detected</span><span /></div>
      {visible.map((signal, index) => <button className="data-row" key={signal.title} onClick={() => index === 0 && go("brief")}>
        <span><b className={`risk-pill ${signal.severity.toLowerCase()}`}>{signal.severity}</b></span>
        <span><strong>{signal.title}</strong><small>{signal.source}</small></span>
        <span><strong>{signal.value}</strong></span><span>{signal.affected}</span><span>{signal.time}</span><span className="row-link">→</span>
      </button>)}
    </div>
  </div>;
}

function Decisions({ go, actions, operationsState, operationsMessage, refresh }: {
  go: (view: View) => void;
  actions: OperationsAction[];
  operationsState: OperationsLoadState;
  operationsMessage: string;
  refresh: () => Promise<void>;
}) {
  if (operationsState === "demo") return <DemoDecisions go={go} />;
  return <div className="page">
    <PageTitle eyebrow="DECIDE" title="Decision queue" copy="Authenticated operational Actions ready for human review." action={<button className="outline-button" onClick={() => void refresh()}>Refresh queue</button>} />
    <OperationsState state={operationsState} message={operationsMessage} label="decision queue" onRetry={refresh} />
    {operationsState === "connected" && <div className="decision-list">
      {actions.filter((item) => item.status === "PROPOSED" || item.status === "EDITED").map((item) => <button className="decision-card" key={item.action_id} onClick={() => go("actions")}>
        <div className={`decision-priority ${item.alert_severity.toLowerCase()}`}><i /><span>{item.alert_severity}</span></div>
        <div className="decision-main"><small>{item.action_id}</small><strong>{item.action_type.replaceAll("_", " ")}</strong><span>Shipment {item.shipment_id}</span></div>
        <div className="decision-value"><small>Alert</small><strong>{item.alert_type.replaceAll("_", " ")}</strong></div>
        <div className="decision-due"><small>{item.action_due_date ? "Due" : "Created"}</small><strong>{item.action_due_date ?? item.created_date}</strong></div>
        <span className="status-button">Review now</span>
      </button>)}
      {actions.every((item) => item.status !== "PROPOSED" && item.status !== "EDITED") && <DataState kind="empty" title="Decision queue is clear" message="No Actions are waiting for human review at this Sydney cutoff." />}
    </div>}
  </div>;
}

function DemoDecisions({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="DECIDE" title="Decision queue" copy="Prioritised recommendations ready for human review." action={<button className="outline-button">Export queue</button>} />
    <div className="queue-summary"><span><strong>3</strong>Waiting for review</span><span><strong>1</strong>Due within 3 hours</span><span><strong>$27.4k</strong>Potential value</span></div>
    <div className="decision-list">{decisions.map((item, index) => <button className="decision-card" key={item.id} onClick={() => index === 0 && go("brief")}>
      <div className={`decision-priority ${item.priority.toLowerCase()}`}><i /><span>{item.priority}</span></div>
      <div className="decision-main"><small>{item.id}</small><strong>{item.title}</strong><span>Owner · {item.owner}</span></div>
      <div className="decision-value"><small>Modelled value</small><strong>{item.value}</strong></div>
      <div className="decision-due"><small>Decision window</small><strong>{item.due}</strong></div>
      <span className="status-button">{item.status} →</span>
    </button>)}</div>
  </div>;
}

function ActionBoard({ actions, operationsState, operationsMessage, submitOperation, refresh }: {
  actions: OperationsAction[];
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
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Action Board" copy="Move approved operational Actions through their governed lifecycle." action={<button className="outline-button" onClick={() => void refresh()}>Refresh board</button>} />
    {operationsState === "demo"
      ? <p className="data-disclaimer">Public demonstration mode is read-only. Configure the internal Operations API and sign in to use the Action Board.</p>
      : <OperationsState state={operationsState} message={operationsMessage} label="Action Board" onRetry={refresh} />}
    {operationsState === "connected" && <>
      {actions.length === 0
        ? <DataState kind="empty" title="No governed Actions" message="There are no Actions available for this authenticated role and cutoff." />
        : <><label className="select-label"><span>Audit reason for the next update</span><input className="operations-reason" value={reason} minLength={3} maxLength={500} onChange={(event) => setReason(event.target.value)} /></label>
        <label className="select-label"><span>Named Action owner (used by Edit)</span><input className="operations-reason" value={actionOwner} maxLength={128} onChange={(event) => setActionOwner(event.target.value)} /></label>
        <label className="select-label"><span>Action due date (used by Edit)</span><input className="operations-reason" type="date" value={actionDueDate} onChange={(event) => setActionDueDate(event.target.value)} /></label>
        <div className="decision-list">{actions.map((item) => <article className="decision-card" key={item.action_id}>
        <div className={`decision-priority ${item.alert_severity.toLowerCase()}`}><i /><span>{item.alert_severity}</span></div>
        <div className="decision-main"><small>{item.action_id}</small><strong>{item.action_type.replaceAll("_", " ")}</strong><span>{item.alert_type.replaceAll("_", " ")} · Shipment {item.shipment_id}</span><span>Owner: {item.action_owner ?? "Unassigned"} · Due: {item.action_due_date ?? "Not set"}</span></div>
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
              <article><small>Immutable proposal</small><strong>{evidence.action.action_type.replaceAll("_", " ")}</strong><span>{evidence.action.created_date} · {evidence.action.status}</span></article>
              <div className="action-audit-events">{evidence.events.length
                ? evidence.events.map((event) => <article key={event.event_id}><i /><div><small>{event.occurred_at}</small><strong>{event.event_type}: {event.previous_status} → {event.new_status}</strong><span>{event.actor} · {event.reason}</span></div></article>)
                : <p>No human mutation has been recorded; the proposal remains unchanged.</p>}
              </div>
              <article className={evidence.outcome?.evidence_status === "OBSERVED_ACTUAL_CALENDAR" ? "observed" : "pending"}><small>Simulated Outcome</small><strong>{evidence.outcome ? evidence.outcome.outcome_status.replaceAll("_", " ") : "Not created"}</strong><span>{evidence.outcome?.evidence_status === "OBSERVED_ACTUAL_CALENDAR" ? `Observed ${evidence.outcome.observed_date} · ${evidence.outcome.effect_pct}% effect` : evidence.outcome ? `Due ${evidence.outcome.observation_due_date} · not observed` : "Requires an approved, completed Action"}</span></article>
            </div>
            <p className="data-disclaimer">The proposal is immutable and audit events are append-only. Outcomes are reproducible synthetic staging evidence, never real logistics performance.</p>
          </>}
        </section>}
      </article>)}</div></>}
    </>}
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
  if (state === "demo") return <div className="page">
    <PageTitle eyebrow="RELIABILITY" title="Pipeline Health" copy="Stage-level operational diagnostics are available only inside the authenticated staging cockpit." />
    <p className="data-disclaimer">The public demonstration does not expose private pipeline stages, infrastructure details, or operational runbooks.</p>
  </div>;
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

function ForecastAccuracy({ contract, state, message, refresh }: {
  contract: ForecastContract | null;
  state: OperationsLoadState;
  message: string;
  refresh: () => Promise<void>;
}) {
  if (state === "demo") return <div className="page">
    <PageTitle eyebrow="PLAN" title="Forecast Accuracy" copy="Operational forecast and backtest evidence is available only inside the authenticated staging cockpit." />
    <p className="data-disclaimer">The public demonstration does not present synthetic engineering results as measured forecast performance.</p>
  </div>;
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
      {shipments.map((item, index) => <button className="shipment-row" key={item.ref} onClick={() => index === 0 && go("brief")}>
        <strong>{item.ref}</strong><span>{item.route}</span><span>{item.eta}</span><span>{item.fcl}</span><span>{item.inventory}</span><span><b className={`risk-pill ${item.risk.toLowerCase()}`}>{item.risk}</b></span><span className="row-link">{item.action} →</span>
      </button>)}
    </div>
    <p className="data-disclaimer">Entity drill-down is available only inside the authenticated staging cockpit; this public workspace remains synthetic.</p>
  </div>;
}

function Outcomes({ outcomes, operationsState, operationsMessage, refresh }: {
  outcomes: OperationsOutcome[];
  operationsState: OperationsLoadState;
  operationsMessage: string;
  refresh: () => Promise<void>;
}) {
  if (operationsState === "demo") return <DemoOutcomes />;
  const pending = outcomes.filter((item) => item.evidence_status === "NOT_OBSERVED");
  const observed = outcomes.filter((item) => item.evidence_status === "OBSERVED_ACTUAL_CALENDAR");
  const successful = observed.filter((item) => ["SUCCESSFUL", "PARTIALLY_SUCCESSFUL"].includes(item.outcome_status));
  const averageEffect = observed.length
    ? `${(observed.reduce((total, item) => total + Number(item.effect_pct ?? 0), 0) / observed.length).toFixed(1)}%`
    : "—";
  return <div className="page">
    <PageTitle eyebrow="LEARN" title="Outcome review" copy="Compare completed Actions with evidence that is mature by the Sydney business-date cutoff." action={<button className="outline-button" onClick={() => void refresh()}>Refresh outcomes</button>} />
    <OperationsState state={operationsState} message={operationsMessage} label="Outcome Review" onRetry={refresh} />
    {operationsState === "connected" && <>
      <section className="metric-grid compact">
        <Metric label="Pending observation" value={String(pending.length)} note="Not counted as actual evidence" tone="amber" />
        <Metric label="Observed outcomes" value={String(observed.length)} note="Actual-calendar evidence only" />
        <Metric label="Successful outcomes" value={String(successful.length)} note={observed.length ? "Observed evidence" : "No mature evidence yet"} tone={successful.length ? "green" : ""} />
        <Metric label="Average observed effect" value={averageEffect} note={observed.length ? "Across mature outcomes" : "Pending outcomes excluded"} />
      </section>
      <div className="decision-list">{outcomes.map((item) => <article className="decision-card" key={item.outcome_id}>
        <div className={`decision-priority ${(item.alert_severity ?? "medium").toLowerCase()}`}><i /><span>{item.outcome_status}</span></div>
        <div className="decision-main"><small>{item.outcome_id}</small><strong>{(item.action_type ?? "Completed Action").replaceAll("_", " ")}</strong><span>Shipment {item.shipment_id} · Action {item.action_id}</span></div>
        <div className="decision-value"><small>{item.evidence_status === "NOT_OBSERVED" ? "Evidence" : "Observed effect"}</small><strong>{item.evidence_status === "NOT_OBSERVED" ? "Not observed" : `${item.effect_pct}%`}</strong></div>
        <div className="decision-due"><small>{item.evidence_status === "NOT_OBSERVED" ? "Observation due" : "Observed"}</small><strong>{item.evidence_status === "NOT_OBSERVED" ? item.observation_due_date : item.observed_date}</strong></div>
        <span className="status-button">{item.evidence_status === "NOT_OBSERVED" ? "Pending" : "Actual calendar"}</span>
      </article>)}</div>
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

function DemoOutcomes() {
  return <div className="page">
    <PageTitle eyebrow="LEARN" title="Outcomes & value" copy="Track whether decisions worked and quantify the value delivered." action={<button className="outline-button">This month⌄</button>} />
    <section className="metric-grid"><Metric label="Decisions executed" value="24" note="89% acceptance rate" /><Metric label="Estimated value" value="$128.4k" note="+18% vs last month" tone="green" /><Metric label="Storage avoided" value="$46.2k" note="12 interventions" /><Metric label="Stockouts prevented" value="7" note="Across 18 critical SKUs" /><Metric label="Forecast accuracy" value="84%" note="+6 pts this quarter" /></section>
    <section className="outcome-grid">
      <article className="card outcome-chart"><CardHead title="Cumulative value delivered" copy="Modelled benefit from accepted recommendations" /><div className="line-chart"><div className="chart-line" /><span className="chart-label l1">$0</span><span className="chart-label l2">$50k</span><span className="chart-label l3">$100k</span><div className="chart-dot" /></div><div className="chart-months"><span>Feb</span><span>Mar</span><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span></div></article>
      <article className="card"><CardHead title="Recent decision outcomes" copy="Expected impact compared with observed result" /><div className="outcome-list">
        <div><i className="success">✓</i><span><strong>Early container collection · Botany</strong><small>Storage avoided · 18 Jul</small></span><b>$9,240</b></div>
        <div><i className="success">✓</i><span><strong>Expedited replenishment · Brisbane</strong><small>Stockout prevented · 14 Jul</small></span><b>$21,800</b></div>
        <div><i className="neutral">—</i><span><strong>Held spot-rate booking · Shanghai</strong><small>Rate unchanged · 11 Jul</small></span><b>$0</b></div>
      </div></article>
    </section>
    <p className="data-disclaimer">All values shown in this demonstration workspace are synthetic and illustrate the intended measurement framework.</p>
  </div>;
}

function DecisionBrief({ diverted, setDiverted, decision, setDecision, economics, go }: {
  diverted: number; setDiverted: (n: number) => void; decision: string;
  setDecision: (v: "pending" | "approved" | "rejected") => void;
  economics: { noAction: number; avoided: number; reroute: number; net: number; stockout: string };
  go: (view: View) => void;
}) {
  return <div className="page brief-page">
    <button className="back-link" onClick={() => go("decisions")}>← Back to decision queue</button>
    <div className="brief-title">
      <div><span className="critical-label">CRITICAL</span><small>DEC-PORT-0001 · Updated 09:30 AEST</small><h1>Protect critical inventory before Sydney port disruption compounds.</h1><p>Congestion is 2.5× baseline and strike probability has reached 82%. Twelve inbound FCL may exceed free storage before inventory cover runs out.</p></div>
      <div className={`decision-status ${decision}`}><span>Decision status</span><strong>{decision === "pending" ? "Pending review" : decision}</strong><small>Owner · Mia Chen</small></div>
    </div>
    <section className="metric-grid compact brief-metrics"><Metric label="Composite risk" value="HIGH" note="Congestion + strike" tone="red" /><Metric label="FCL exposed" value="12" note="Critical SKU cargo" /><Metric label="Cost exposure" value={money(economics.noAction)} note="Without action" /><Metric label="Inventory cover" value="8 days" note="vs 9-day dwell" /></section>
    <section className="brief-grid">
      <article className="card"><CardHead title="Why the risk escalated" copy="Signals crossed intervention thresholds" /><div className="signal-meter"><span>Port congestion index <b>0.87</b></span><div><i style={{width:"87%"}} /></div><small>Baseline 0.35</small></div><div className="signal-meter amber"><span>Labour-strike probability <b>82%</b></span><div><i style={{width:"82%"}} /></div><small>Escalation threshold 60%</small></div><div className="cover-compare"><div><span>Inventory cover</span><strong>8 days</strong></div><b>1-day gap</b><div><span>Expected dwell</span><strong>9 days</strong></div></div></article>
      <article className="card"><CardHead title="Recommended action" copy="80% model confidence" /><div className="recommendation"><i>↗</i><div><strong>Divert {diverted} high-priority FCL to Melbourne</strong><p>Move cargo to Sydney DC by rail or truck. Keep {12-diverted} lower-priority FCL on the original route and review daily.</p></div></div><div className="route-flow"><div><i className="red" /><strong>Sydney</strong><span>Disrupted</span></div><b>→ <small>{diverted} FCL</small></b><div><i className="blue" /><strong>Melbourne</strong><span>Alternate</span></div><b>→ <small>Rail</small></b><div><i className="green" /><strong>Sydney DC</strong><span>Protected</span></div></div></article>
      <article className="card"><CardHead title="Decision economics" copy="Scenario changes with diversion volume" /><div className="economics-list"><div><span>No-action exposure</span><strong>{money(economics.noAction)}</strong></div><div><span>Avoided storage</span><strong className="green-text">+{money(economics.avoided)}</strong></div><div><span>Reroute cost</span><strong className="amber-text">−{money(economics.reroute)}</strong></div></div><div className="net-benefit"><span>Net modelled benefit</span><strong>{money(economics.net)}</strong><small>Stockout risk after action · <b>{economics.stockout}</b></small></div></article>
      <article className="card review-card"><CardHead title="Operator review" copy="Human approval required before execution" /><label className="range-label"><span>FCL to divert <strong>{diverted}</strong></span><input aria-label="FCL to divert" type="range" min="0" max="12" value={diverted} onChange={(e) => {setDiverted(Number(e.target.value)); setDecision("pending");}} /><small><span>0</span><span>Recommended · 8</span><span>12</span></small></label><label className="select-label"><span>Decision owner</span><select><option>Mia Chen · Import Operations</option><option>James Wu · Inventory Planning</option><option>Sarah Lim · Control Tower</option></select></label><div className="rationale"><span>Decision rationale</span><p>Expected dwell exceeds inventory cover and free-storage time. Selective diversion protects critical inventory while limiting unnecessary reroute cost.</p></div><div className="decision-buttons"><button onClick={() => setDecision("rejected")}>Reject</button><button onClick={() => setDecision("approved")}>Approve diversion</button></div><small className="demo-note">Demonstration only · no instruction is sent to a carrier or terminal.</small></article>
    </section>
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
