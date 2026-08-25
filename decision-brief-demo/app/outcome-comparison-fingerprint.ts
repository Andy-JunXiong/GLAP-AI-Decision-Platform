import type { OutcomeComparisonCohort } from "./operations-api";

export type OutcomeComparisonFingerprintReason =
  | "MATCH"
  | "MISSING_INTEGRITY"
  | "CONTRACT_METADATA_MISMATCH"
  | "CRYPTO_UNAVAILABLE"
  | "NON_CANONICAL_CONTENT"
  | "DIGEST_MISMATCH"
  | "VERIFICATION_ERROR";

export type OutcomeComparisonFingerprintVerification = {
  status: "VERIFIED" | "MISMATCH";
  reason_code: OutcomeComparisonFingerprintReason;
};

const RETRYABLE_REASON_CODES = new Set<OutcomeComparisonFingerprintReason>([
  "CRYPTO_UNAVAILABLE",
  "VERIFICATION_ERROR",
]);

export function isOutcomeComparisonFingerprintRetryable(
  verification: OutcomeComparisonFingerprintVerification,
): boolean {
  return verification.status === "MISMATCH"
    && RETRYABLE_REASON_CODES.has(verification.reason_code);
}

const EXPECTED_COVERED_FIELDS = [
  "decision_brief_version",
  "selected_alternative",
  "observed_outcome_count",
  "status_percentages",
  "effect_pct",
  "provenance",
] as const;

function fixedTwoDecimal(value: number): string {
  if (!Number.isFinite(value)) throw new Error("Percentage is not finite");
  const normalized = value === 0 ? 0 : value;
  const text = normalized.toFixed(2);
  if (Number(text) !== normalized) {
    throw new Error("Percentage exceeds the two-decimal comparison contract");
  }
  return text;
}

function sortCanonicalValue(value: unknown): unknown {
  if (value === null || typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (/[^\x00-\x7f]/.test(value)) throw new Error("Canonical strings must be ASCII");
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("Canonical numbers must be safe integers");
    return value;
  }
  if (Array.isArray(value)) return value.map(sortCanonicalValue);
  if (typeof value !== "object" || Object.getPrototypeOf(value) !== Object.prototype) {
    throw new Error("Unsupported canonical value");
  }
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => {
      if (/[^\x00-\x7f]/.test(key)) throw new Error("Canonical keys must be ASCII");
      return [key, sortCanonicalValue((value as Record<string, unknown>)[key])];
    }),
  );
}

function metadataMatches(cohort: OutcomeComparisonCohort): boolean {
  const integrity = cohort.integrity;
  if (!integrity) return false;
  return integrity.schema_version === "outcome-cohort-comparison-fingerprint.v1"
    && integrity.algorithm === "SHA-256"
    && integrity.canonicalization === "JSON_SORT_KEYS_COMPACT_UTF8_ASCII_DECIMAL_2_STRINGS"
    && integrity.verification_scope === "RESPONSE_CONTENT_INTEGRITY_ONLY"
    && integrity.digital_signature === false
    && integrity.source_authenticity_attested === false
    && integrity.business_validity_attested === false
    && /^[0-9a-f]{64}$/.test(integrity.digest)
    && integrity.covered_fields.length === EXPECTED_COVERED_FIELDS.length
    && integrity.covered_fields.every(
      (field, index) => field === EXPECTED_COVERED_FIELDS[index],
    );
}

export function canonicalOutcomeComparisonFingerprintPayload(
  cohort: OutcomeComparisonCohort,
): string {
  if (!Number.isSafeInteger(cohort.observed_outcome_count)
    || cohort.observed_outcome_count < 1) {
    throw new Error("Observed Outcome count is invalid");
  }
  const payload = {
    decision_brief_version: cohort.decision_brief_version,
    selected_alternative: cohort.selected_alternative,
    observed_outcome_count: cohort.observed_outcome_count,
    status_percentages: Object.fromEntries(
      Object.entries(cohort.status_percentages).map(
        ([key, value]) => [key, fixedTwoDecimal(value)],
      ),
    ),
    effect_pct: Object.fromEntries(
      Object.entries(cohort.effect_pct).map(
        ([key, value]) => [key, fixedTwoDecimal(value)],
      ),
    ),
    provenance: cohort.provenance,
  };
  return JSON.stringify(sortCanonicalValue(payload));
}

export async function verifyOutcomeComparisonFingerprint(
  cohort: OutcomeComparisonCohort,
): Promise<OutcomeComparisonFingerprintVerification> {
  if (!cohort.integrity) {
    return { status: "MISMATCH", reason_code: "MISSING_INTEGRITY" };
  }
  if (!metadataMatches(cohort)) {
    return { status: "MISMATCH", reason_code: "CONTRACT_METADATA_MISMATCH" };
  }
  if (!globalThis.crypto?.subtle) {
    return { status: "MISMATCH", reason_code: "CRYPTO_UNAVAILABLE" };
  }
  let canonicalPayload: string;
  try {
    canonicalPayload = canonicalOutcomeComparisonFingerprintPayload(cohort);
  } catch {
    return { status: "MISMATCH", reason_code: "NON_CANONICAL_CONTENT" };
  }
  try {
    const digestBytes = await globalThis.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonicalPayload),
    );
    const computedDigest = Array.from(new Uint8Array(digestBytes))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    return computedDigest === cohort.integrity.digest
      ? { status: "VERIFIED", reason_code: "MATCH" }
      : { status: "MISMATCH", reason_code: "DIGEST_MISMATCH" };
  } catch {
    return { status: "MISMATCH", reason_code: "VERIFICATION_ERROR" };
  }
}
