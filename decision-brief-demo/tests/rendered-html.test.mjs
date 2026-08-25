import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the GLAP customer control tower", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>GLAP Logistics Decision Platform<\/title>/i);
  assert.match(html, /Control Tower/);
  assert.match(html, /Network risk picture/);
  assert.match(html, /Needs your attention/);
  assert.match(html, /Divert 8 FCL via Melbourne/);
  assert.match(html, /Illustrative scenario value/);
  assert.match(html, /data-claim-id="next-portfolio-value"/);
  assert.match(html, /Fixed illustrative portfolio · not execution evidence/);
  assert.match(html, /Action Board/);
  assert.match(html, /property="og:image" content="\/og\.png"/);
});

test("includes the generated social card", async () => {
  await access(new URL("../public/og.png", import.meta.url));
});

test("keeps authenticated Action writes behind the internal API client", async () => {
  const client = await readFile(new URL("../app/operations-api.ts", import.meta.url), "utf8");
  assert.match(client, /NEXT_PUBLIC_GLAP_OPERATIONS_API_URL/);
  assert.match(client, /sessionStorage\.getItem/);
  assert.match(client, /authorization: `Bearer \$\{token\}`/);
  assert.match(client, /\/v1\/actions\/\$\{encodeURIComponent\(actionId\)\}\/events/);
  assert.match(client, /\/v1\/actions\/\$\{encodeURIComponent\(actionId\)\}\/evidence/);
  assert.match(client, /export async function loadActionEvidence/);
  assert.match(client, /"EDIT" \| "APPROVE" \| "REJECT" \| "COMPLETE"/);
  assert.match(client, /action_owner: assignment\.actionOwner/);
  assert.match(client, /action_due_date: assignment\.actionDueDate/);
  assert.match(client, /\/v1\/risks\$\{query\}/);
  assert.match(client, /export async function loadRiskHotspots/);
  assert.match(client, /\/v1\/outcomes\$\{query\}/);
  assert.match(client, /export async function loadOutcomeReview/);
  assert.match(client, /\/v1\/learning/);
  assert.match(client, /export async function loadLearningEvidence/);
  assert.match(client, /\/v1\/label-readiness/);
  assert.match(client, /export async function loadLabelReadiness/);
  assert.match(client, /\/v1\/pipeline-health/);
  assert.match(client, /export async function loadPipelineHealth/);
  assert.match(client, /\/v1\/forecasts/);
  assert.match(client, /export async function loadForecastAccuracy/);
  assert.match(client, /\/v1\/network/);
  assert.match(client, /export async function loadNetworkSummary/);
  assert.match(client, /\/v1\/shipments/);
  assert.match(client, /export async function loadShipmentDrilldown/);
  assert.doesNotMatch(client, /localStorage/);

  const auth = await readFile(new URL("../app/operations-auth.ts", import.meta.url), "utf8");
  assert.match(auth, /code_challenge_method: "S256"/);
  assert.match(auth, /returnedState !== expectedState/);
  assert.match(auth, /window\.sessionStorage/);
  assert.doesNotMatch(auth, /localStorage/);

  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /loadRiskHotspots\(token, "OPEN"\)/);
  assert.match(page, /title="Risk hotspots"/);
  assert.match(page, /risk\.decision_brief \? openBrief\(risk\.decision_brief\)/);
  assert.match(page, /function OperationalDecisionBrief/);
  assert.match(page, /Expected benefit" value="NOT ESTIMATED"/);
  assert.match(page, /This brief itself performs no mutation/);
  assert.match(page, /Bound to \$\{item\.decision_brief_version\}/);
  assert.match(page, /selected deterministic alternative/);
  assert.match(page, /Named-human review reasons remain append-only audit events/);
  assert.match(client, /decision_brief_version: "decision-brief\.v1" \| null/);
  assert.match(client, /decision_binding_immutable: true/);
  assert.match(page, /onClick=\{\(\) => go\("decisions"\)\}/);
  assert.match(page, /loadOutcomeReview\(token\)/);
  assert.match(page, /title="Outcome review"/);
  assert.match(page, /Not counted as actual evidence/);
  assert.match(page, /OBSERVED_ACTUAL_CALENDAR/);
  assert.match(page, /title="Pipeline Health"/);
  assert.match(page, /Open recovery runbook/);
  assert.match(page, /Future simulations cannot be presented as current pipeline health/);
  assert.match(page, /title="Forecast Accuracy"/);
  assert.match(page, /Model promotion remains blocked/);
  assert.match(page, /future points remain unobserved projections/);
  assert.match(page, /title="Network Drill-down"/);
  assert.match(page, /shipment identifiers require an operator, approver, or administrator role/);
  assert.match(page, /Costs, raw port identifiers, infrastructure identifiers, and future simulations are excluded/);
  assert.match(page, /type DataStateKind = "loading" \| "empty" \| "stale" \| "partial" \| "failed"/);
  assert.match(page, /aria-live=\{failed \? "assertive" : "polite"\}/);
  assert.match(page, /aria-busy=\{kind === "loading"\}/);
  assert.match(page, /Pipeline evidence is stale/);
  assert.match(page, /Forecast evidence is incomplete/);
  assert.match(page, /Some shipment evidence is still available/);
  assert.match(page, /Assign &amp; edit/);
  assert.match(page, /item\.status === "EDITED"/);
  assert.match(page, /const succeeded = await submitOperation/);
  assert.match(page, /reviewEvidence = async \(actionId: string, forceRefresh = false\)/);
  assert.match(page, /!forceRefresh && selectedEvidence === actionId/);
  assert.match(page, /succeeded && selectedEvidence === action\.action_id/);
  assert.match(page, /await reviewEvidence\(action\.action_id, true\)/);
  assert.match(page, /Action–Outcome evidence chain/);
  assert.match(page, /The proposal is immutable and audit events are append-only/);
  assert.match(page, /never real logistics performance/);
  assert.match(page, /title="Learning Review"/);
  assert.match(page, /Learning evidence is not yet eligible/);
  assert.match(page, /Policy activation always requires a separate named-human approval/);
  assert.match(page, /synthetic policy-review evidence only/);
  assert.match(page, /deterministic safety rules remain in force/);
  assert.match(page, /title="Provider Label Readiness"/);
  assert.match(page, /Supervised evaluation remains blocked/);
  assert.match(page, /Pending labels and future simulations never count/);
  assert.match(page, /model training, model promotion, deployment, recurring prediction, and production readiness remain unauthorized/);
  assert.match(page, /Try again/);

  const operationsCss = await readFile(new URL("../app/operations.css", import.meta.url), "utf8");
  assert.match(operationsCss, /\.data-state\.loading/);
  assert.match(operationsCss, /\.data-state\.stale, \.data-state\.partial/);
  assert.match(operationsCss, /\.data-state\.failed/);
  assert.match(operationsCss, /prefers-reduced-motion: reduce/);
  assert.match(operationsCss, /\.action-evidence-flow/);
  assert.match(operationsCss, /\.learning-proposal/);
  assert.match(operationsCss, /\.label-readiness-grid/);
  assert.match(operationsCss, /\.label-targets/);
});
