"use client";

import { useMemo, useState } from "react";

const TOTAL_FCL = 12;
const CHARGEABLE_DAYS = 6;
const STORAGE_PER_DAY = 220;
const REROUTE_PER_FCL = 600;

export default function Home() {
  const [diverted, setDiverted] = useState(8);
  const [owner, setOwner] = useState("Mia Chen · Import Operations");
  const [decision, setDecision] = useState<"pending" | "approved" | "rejected">("pending");

  const economics = useMemo(() => {
    const noAction = TOTAL_FCL * CHARGEABLE_DAYS * STORAGE_PER_DAY;
    const avoided = diverted * CHARGEABLE_DAYS * STORAGE_PER_DAY;
    const reroute = diverted * REROUTE_PER_FCL;
    const net = avoided - reroute;
    const stockoutRisk = diverted >= 8 ? "Low" : diverted >= 5 ? "Medium" : "High";
    return { noAction, avoided, reroute, net, stockoutRisk };
  }, [diverted]);

  const money = (value: number) =>
    new Intl.NumberFormat("en-AU", {
      style: "currency",
      currency: "AUD",
      maximumFractionDigits: 0,
    }).format(value);

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">G</span>
          <div>
            <strong>GLAP</strong>
            <span>Decision Intelligence</span>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="live-dot"><i /> Synthetic scenario</span>
          <span className="run-id">DEC-PORT-0001</span>
        </div>
      </header>

      <section className="hero shell">
        <div className="eyebrow"><span>HIGH PRIORITY</span> Port disruption brief</div>
        <div className="hero-copy">
          <div>
            <h1>Protect critical inventory before Sydney port disruption compounds.</h1>
            <p>
              Congestion is 2.5× baseline and labour-strike probability has reached 82%.
              Twelve inbound FCL containers will exceed free storage before current inventory cover runs out.
            </p>
          </div>
          <div className={`decision-state ${decision}`}>
            <span>Decision status</span>
            <strong>{decision === "pending" ? "Pending review" : decision}</strong>
          </div>
        </div>
      </section>

      <section className="kpi-grid shell" aria-label="Decision KPIs">
        <article className="kpi risk">
          <span>Composite risk</span><strong>HIGH</strong><small>Congestion + strike</small>
        </article>
        <article className="kpi">
          <span>FCL exposed</span><strong>12</strong><small>Critical SKU cargo</small>
        </article>
        <article className="kpi">
          <span>Storage exposure</span><strong>{money(economics.noAction)}</strong><small>Without action</small>
        </article>
        <article className="kpi">
          <span>Inventory cover</span><strong>8 days</strong><small>vs 9-day dwell</small>
        </article>
        <article className="kpi">
          <span>Strike probability</span><strong>82%</strong><small>Escalation threshold 60%</small>
        </article>
      </section>

      <section className="content-grid shell">
        <article className="panel signal-panel">
          <div className="panel-head">
            <div><span className="section-tag">01 · DETECT</span><h2>Why the risk escalated</h2></div>
            <span className="timestamp">Updated 09:00 AEST</span>
          </div>
          <div className="signal-list">
            <div className="signal-row">
              <div><span>Port congestion index</span><strong>0.87</strong></div>
              <div className="meter"><i style={{ width: "87%" }} /></div>
              <small>Baseline 0.35</small>
            </div>
            <div className="signal-row">
              <div><span>Labour-strike probability</span><strong>82%</strong></div>
              <div className="meter amber"><i style={{ width: "82%" }} /></div>
              <small>Escalation threshold 60%</small>
            </div>
            <div className="timeline-compare">
              <div><span>Inventory cover</span><b>8</b><small>days</small></div>
              <div className="gap"><span>1-day gap</span></div>
              <div><span>Expected dwell</span><b>9</b><small>days</small></div>
            </div>
          </div>
        </article>

        <article className="panel action-panel">
          <div className="panel-head">
            <div><span className="section-tag">02 · DECIDE</span><h2>Recommended action</h2></div>
            <span className="confidence">80% confidence</span>
          </div>
          <div className="recommendation">
            <div className="action-icon">↗</div>
            <div>
              <h3>Divert {diverted} high-priority FCL to Melbourne</h3>
              <p>Move diverted cargo to the Sydney DC by rail or truck. Keep {TOTAL_FCL - diverted} lower-priority FCL on the original route and review daily.</p>
            </div>
          </div>
          <div className="route" aria-label="Proposed container route">
            <div className="route-node blocked"><i /><strong>Sydney Port</strong><span>Disrupted</span></div>
            <div className="route-line"><span>{diverted} FCL diverted</span></div>
            <div className="route-node alternate"><i /><strong>Melbourne Port</strong><span>Alternate</span></div>
            <div className="route-line rail"><span>Rail / truck</span></div>
            <div className="route-node dc"><i /><strong>Sydney DC</strong><span>Protected</span></div>
          </div>
        </article>

        <article className="panel economics-panel">
          <div className="panel-head">
            <div><span className="section-tag">03 · QUANTIFY</span><h2>Decision economics</h2></div>
            <span className="synthetic-pill">Modelled</span>
          </div>
          <div className="bar-chart">
            <div className="bar-row"><span>No action exposure</span><div><i className="bar danger" style={{ width: "100%" }} /></div><strong>{money(economics.noAction)}</strong></div>
            <div className="bar-row"><span>Avoided storage</span><div><i className="bar saving" style={{ width: `${(economics.avoided / economics.noAction) * 100}%` }} /></div><strong>{money(economics.avoided)}</strong></div>
            <div className="bar-row"><span>Reroute cost</span><div><i className="bar cost" style={{ width: `${(economics.reroute / economics.noAction) * 100}%` }} /></div><strong>{money(economics.reroute)}</strong></div>
          </div>
          <div className="net-result">
            <div><span>Net modelled benefit</span><strong>{money(economics.net)}</strong></div>
            <div><span>Stockout risk after action</span><strong className={economics.stockoutRisk.toLowerCase()}>{economics.stockoutRisk}</strong></div>
          </div>
        </article>

        <article className="panel review-panel">
          <div className="panel-head">
            <div><span className="section-tag">04 · REVIEW</span><h2>Operator decision</h2></div>
            <span className="required">Human review required</span>
          </div>
          <label className="slider-label">
            <span>FCL to divert <strong>{diverted}</strong></span>
            <input type="range" min="0" max="12" value={diverted} onChange={(event) => { setDiverted(Number(event.target.value)); setDecision("pending"); }} />
            <small><span>0</span><span>Recommended: 8</span><span>12</span></small>
          </label>
          <label className="owner-field">
            <span>Decision owner</span>
            <select value={owner} onChange={(event) => setOwner(event.target.value)}>
              <option>Mia Chen · Import Operations</option>
              <option>James Wu · Inventory Planning</option>
              <option>Sarah Lim · Logistics Control Tower</option>
            </select>
          </label>
          <div className="review-note">
            <span>Decision rationale</span>
            <p>Expected dwell exceeds inventory cover and free storage time. Selective diversion protects the critical SKU while limiting unnecessary reroute cost.</p>
          </div>
          <div className="decision-actions">
            <button className="secondary" onClick={() => setDecision("rejected")}>Reject</button>
            <button className="primary" onClick={() => setDecision("approved")}>Approve diversion</button>
          </div>
          <p className="demo-note">Demo only — no operational instruction is sent.</p>
        </article>
      </section>

      <footer className="shell">
        <span>GLAP · AWS-deployed reference implementation</span>
        <span>Scenario values and outcomes are synthetic</span>
      </footer>
    </main>
  );
}
