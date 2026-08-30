import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  SYSTEM_EVIDENCE_SCHEMA_VERSION,
  currentSydneyDate,
  validateSystemEvidenceSnapshot,
} from "../app/system-evidence-snapshot.ts";

export const SOURCE_SCHEMA_VERSION = "system-evidence-source.v2";
export const SOURCE_DOCUMENTS = [
  "../INFRASTRUCTURE.md",
  "../docs/architecture_current.md",
  "../docs/deployment_workflow.md",
  "../docs/ops_snapshot.md",
];

const sourcePath = new URL("../contracts/system-evidence-source.v2.json", import.meta.url);
const outputPath = new URL("../public/data/system-evidence-snapshot.json", import.meta.url);

const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
const exactKeys = (value, keys) => Object.keys(value).sort().join("|") === [...keys].sort().join("|");

export function buildSystemEvidenceSnapshot(source, sydneyDate = currentSydneyDate()) {
  if (!isRecord(source) || !exactKeys(source, ["schema_version", "source_documents", "public_snapshot"])
    || source.schema_version !== SOURCE_SCHEMA_VERSION
    || !Array.isArray(source.source_documents)
    || source.source_documents.length !== SOURCE_DOCUMENTS.length
    || source.source_documents.some((value, index) => value !== SOURCE_DOCUMENTS[index])
    || !isRecord(source.public_snapshot)
  ) throw new Error("SYSTEM_EVIDENCE_SOURCE_INVALID");

  return validateSystemEvidenceSnapshot({
    schema_version: SYSTEM_EVIDENCE_SCHEMA_VERSION,
    ...source.public_snapshot,
  }, sydneyDate);
}

export const serializeSystemEvidenceSnapshot = (snapshot) => `${JSON.stringify(snapshot, null, 2)}\n`;

export async function generateSystemEvidenceSnapshot({ check = false, sydneyDate = currentSydneyDate() } = {}) {
  const source = JSON.parse(await readFile(sourcePath, "utf8"));
  const expected = serializeSystemEvidenceSnapshot(buildSystemEvidenceSnapshot(source, sydneyDate));

  if (check) {
    const current = await readFile(outputPath, "utf8");
    if (current !== expected) throw new Error("SYSTEM_EVIDENCE_SNAPSHOT_DRIFT");
    return { status: "verified", output: fileURLToPath(outputPath) };
  }

  await writeFile(outputPath, expected, "utf8");
  return { status: "generated", output: fileURLToPath(outputPath) };
}

const invokedPath = process.argv[1] ? fileURLToPath(import.meta.url) === process.argv[1] : false;
if (invokedPath) {
  const check = process.argv.slice(2).includes("--check");
  generateSystemEvidenceSnapshot({ check })
    .then((result) => console.log(`System evidence snapshot ${result.status}.`))
    .catch((error) => {
      console.error(error instanceof Error ? error.message : "SYSTEM_EVIDENCE_GENERATION_FAILED");
      process.exitCode = 1;
    });
}
