#!/usr/bin/env node

/** Build the compact, display-only story bundle used by the Lambda reviewer. */

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { attachStoryProfiles } from "../blinded-review-survey/lib/server-story-profiles.ts";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourcePath = resolve(root, "blinded-review-survey/data/review-bundle.json");
const outputPath = resolve(root, "lambda/ten_story_review_bundle.json");
const sourceBundle = JSON.parse(await readFile(sourcePath, "utf8"));
const packages = attachStoryProfiles(sourceBundle.packages);

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function visibleOptionsMatch(item) {
  if (item.options.length !== 2) return false;
  const [left, right] = item.options;
  return left.recommendation === right.recommendation
    && left.priority === right.priority
    && left.human_review_required === right.human_review_required
    && left.rationale === right.rationale
    && JSON.stringify(left.content) === JSON.stringify(right.content);
}

function option(item, profile, stageIndex, optionIndex) {
  const source = item.options[optionIndex];
  const mitigation = source.recommendation === "RISK_MITIGATION";
  return {
    id: optionIndex === 0 ? "A" : "B",
    title: mitigation ? profile.mitigationTitle : profile.monitorTitle,
    body: mitigation ? profile.mitigationActions[stageIndex] : profile.monitorActions[stageIndex],
    tradeoff: mitigation ? profile.mitigationTradeoffs[stageIndex] : profile.monitorTradeoffs[stageIndex],
  };
}

const groups = new Map();
for (const item of packages) {
  const id = item.scenario.story_profile.id;
  groups.set(id, [...(groups.get(id) ?? []), item]);
}
if (groups.size !== 10) throw new Error(`Expected 10 stories; received ${groups.size}`);

const cases = [...groups.values()].map((group) => {
  const ordered = [...group].sort((left, right) => new Date(left.scenario.cutoff_at) - new Date(right.scenario.cutoff_at));
  if (ordered.length !== 3) throw new Error(`Expected 3 moments for ${ordered[0].scenario.story_profile.id}`);
  const profile = ordered[0].scenario.story_profile;
  return {
    id: profile.id,
    title: profile.shortTitle,
    role: profile.role,
    region: profile.regionLabel,
    disruption: profile.disruptionLabel,
    decision_lens: profile.decisionLens,
    story_intro: profile.storyIntro,
    goal: profile.goal,
    stakes: profile.stakes,
    mode: ordered[0].scenario.scenario_profile.transport_mode,
    stages: ordered.map((item, index) => ({
      review_id: item.review_id,
      package_digest: item.package_digest,
      moment: ["T0", "T1", "T2"][index],
      cutoff_at: item.scenario.cutoff_at,
      status: profile.statuses[index],
      update: profile.updates[index],
      unknown: profile.unknowns[index],
      question: profile.questions[index],
      inventory_cover_days: item.scenario.operational_state.inventory_cover_days,
      alternate_capacity_available: item.scenario.operational_state.alternate_capacity_available,
      shared_plan: visibleOptionsMatch(item),
      options: [option(item, profile, index, 0), option(item, profile, index, 1)],
    })),
  };
});

const output = {
  schema_version: "glap-ten-story-display-bundle.v1",
  source_bundle_id: sourceBundle.bundle_id,
  source_bundle_digest: sourceBundle.bundle_digest,
  source_package_count: sourceBundle.package_count,
  cases,
};
output.bundle_digest = createHash("sha256").update(canonical(output)).digest("hex");
await writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`, "utf8");
console.log(`created=${outputPath}`);
console.log(`cases=${cases.length}`);
console.log(`moments=${cases.reduce((count, item) => count + item.stages.length, 0)}`);
console.log(`sha256=${output.bundle_digest}`);
