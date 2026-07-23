"use client";

import { useMemo, useState } from "react";

type View = "overview" | "signals" | "decisions" | "shipments" | "outcomes" | "brief";

const navItems: { id: View; label: string; icon: string }[] = [
  { id: "overview", label: "Control Tower", icon: "⌂" },
  { id: "signals", label: "Signals", icon: "⌁" },
  { id: "decisions", label: "Decisions", icon: "◇" },
  { id: "shipments", label: "Shipments", icon: "▣" },
  { id: "outcomes", label: "Outcomes", icon: "↗" },
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
          {navItems.map((item) => (
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
            <span className="demo-badge">Synthetic workspace</span>
            <button aria-label="Notifications" className="notification">●<b>3</b></button>
            <button className="help">?</button>
          </div>
        </header>

        {view === "overview" && <Overview go={go} />}
        {view === "signals" && <Signals filter={signalFilter} setFilter={setSignalFilter} go={go} />}
        {view === "decisions" && <Decisions go={go} />}
        {view === "shipments" && <Shipments go={go} />}
        {view === "outcomes" && <Outcomes />}
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

function Signals({ filter, setFilter, go }: { filter: string; setFilter: (v: string) => void; go: (view: View) => void }) {
  const visible = filter === "All" ? signals : signals.filter((signal) => signal.severity === filter);
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

function Decisions({ go }: { go: (view: View) => void }) {
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

function Shipments({ go }: { go: (view: View) => void }) {
  return <div className="page">
    <PageTitle eyebrow="OPERATE" title="Shipments & inventory" copy="Connect network risks to the cargo and inventory they affect." action={<button className="primary-button">＋ Add shipment</button>} />
    <section className="metric-grid compact"><Metric label="Active shipments" value="46" note="21 inbound FCL" /><Metric label="Delayed" value="11" note="4 over 48 hours" tone="amber" /><Metric label="At-risk FCL" value="15" note="Across 2 ports" tone="red" /><Metric label="Critical SKUs" value="6" note="Below 10 days cover" /></section>
    <div className="table-card shipment-table">
      <div className="shipment-row table-head"><span>Reference</span><span>Route</span><span>ETA</span><span>FCL</span><span>Inventory cover</span><span>Risk</span><span>Action</span></div>
      {shipments.map((item, index) => <button className="shipment-row" key={item.ref} onClick={() => index === 0 && go("brief")}>
        <strong>{item.ref}</strong><span>{item.route}</span><span>{item.eta}</span><span>{item.fcl}</span><span>{item.inventory}</span><span><b className={`risk-pill ${item.risk.toLowerCase()}`}>{item.risk}</b></span><span className="row-link">{item.action} →</span>
      </button>)}
    </div>
  </div>;
}

function Outcomes() {
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
