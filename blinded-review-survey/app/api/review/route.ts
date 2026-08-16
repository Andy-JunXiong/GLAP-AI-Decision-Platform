import reviewBundle from "@/data/review-bundle.json";
import rubric from "@/data/rubric.json";
import { requireReviewer, sameOrigin } from "../../account-auth";
import { getD1 } from "@/db/runtime";
import { DIMENSION_IDS, type Locale, type Preference, type ReviewAnswer, type Scores } from "@/lib/review-types";
import { TRANSLATION_VERSION } from "@/lib/translations";
import { localizeReviewPackages } from "@/lib/server-review-translations";

export const dynamic = "force-dynamic";

type D1Row = Record<string, unknown>;

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status });
}

function isScore(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0 && Number(value) <= 4;
}

function validScores(value: unknown): value is Scores {
  if (!value || typeof value !== "object") return false;
  const scores = value as Record<string, unknown>;
  return DIMENSION_IDS.every((id) => scores[id] === null || isScore(scores[id]));
}

function validAnswer(value: unknown): value is ReviewAnswer {
  if (!value || typeof value !== "object") return false;
  const answer = value as Partial<ReviewAnswer>;
  return (
    typeof answer.reviewId === "string" &&
    typeof answer.packageDigest === "string" &&
    validScores(answer.optionA) &&
    validScores(answer.optionB) &&
    (answer.preferred === null || ["OPTION_A", "OPTION_B", "TIE"].includes(String(answer.preferred))) &&
    (answer.confidence === null || (Number.isInteger(answer.confidence) && Number(answer.confidence) >= 1 && Number(answer.confidence) <= 5)) &&
    typeof answer.notes === "string" &&
    answer.notes.length <= 1000
  );
}

function answerComplete(answer: ReviewAnswer) {
  return (
    DIMENSION_IDS.every((id) => isScore(answer.optionA[id])) &&
    DIMENSION_IDS.every((id) => isScore(answer.optionB[id])) &&
    answer.preferred !== null &&
    answer.confidence !== null
  );
}

function packageFor(reviewId: string) {
  return reviewBundle.packages.find((item) => item.review_id === reviewId);
}

async function sessionFor(db: D1Database, userId: string) {
  return db.prepare("SELECT * FROM review_sessions WHERE user_id = ? AND bundle_id = ? LIMIT 1")
    .bind(userId, reviewBundle.bundle_id)
    .first<D1Row>();
}

function deserializeAnswer(row: D1Row): ReviewAnswer {
  return {
    reviewId: String(row.review_id),
    packageDigest: String(row.package_digest),
    optionA: JSON.parse(String(row.option_a_scores)) as Scores,
    optionB: JSON.parse(String(row.option_b_scores)) as Scores,
    preferred: (row.preferred ? String(row.preferred) : null) as Preference | null,
    confidence: row.confidence === null ? null : Number(row.confidence),
    notes: String(row.notes ?? ""),
  };
}

export async function GET(request: Request) {
  try {
    const reviewer = await requireReviewer(request);
    const db = getD1();
    const session = await sessionFor(db, reviewer.userId);
    const result = session
      ? await db.prepare("SELECT * FROM review_answers WHERE session_id = ? ORDER BY id").bind(session.id).all<D1Row>()
      : { results: [] as D1Row[] };
    return Response.json({
      bootstrap: {
        bundleId: reviewBundle.bundle_id,
        bundleDigest: reviewBundle.bundle_digest,
        packages: localizeReviewPackages(reviewBundle.packages),
        dimensions: rubric.dimensions,
      },
      session: session ? {
        locale: session.locale,
        status: session.status,
        currentIndex: Number(session.current_index),
        submittedAt: session.submitted_at,
      } : null,
      answers: result.results.map(deserializeAnswer),
    }, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    if (error instanceof Response) return error;
    return jsonError(error instanceof Error ? error.message : "Unable to load review", 500);
  }
}

export async function POST(request: Request) {
  try {
    if (!sameOrigin(request)) return jsonError("Request origin rejected", 403);
    const reviewer = await requireReviewer(request);
    const payload = (await request.json()) as Record<string, unknown>;
    const action = String(payload.action ?? "");
    const db = getD1();
    const now = new Date().toISOString();

    if (action === "start") {
      const locale: Locale = payload.locale === "en" ? "en" : "zh";
      const attestations = payload.attestations as Record<string, unknown> | undefined;
      if (attestations?.independent !== true || attestations?.noConflict !== true || attestations?.noBlindKey !== true) {
        return jsonError("All eligibility attestations are required");
      }
      const existing = await sessionFor(db, reviewer.userId);
      if (existing?.status === "SUBMITTED") return jsonError("Review is already submitted", 409);
      if (!existing) {
        await db.prepare(
          `INSERT INTO review_sessions
          (user_id, bundle_id, bundle_digest, reviewer_ref, locale, translation_version, independent_attested,
           no_conflict_attested, no_blind_key_attested, status, current_index, created_at, updated_at)
          VALUES (?, ?, ?, 'reviewer-ops-01', ?, ?, 1, 1, 1, 'DRAFT', 0, ?, ?)`,
        ).bind(
          reviewer.userId,
          reviewBundle.bundle_id,
          reviewBundle.bundle_digest,
          locale,
          TRANSLATION_VERSION,
          now,
          now,
        ).run();
      }
      return Response.json({ ok: true });
    }

    const session = await sessionFor(db, reviewer.userId);
    if (!session) return jsonError("Start the review first", 409);
    if (session.status === "SUBMITTED") return jsonError("Review is already submitted", 409);

    if (action === "save") {
      if (!validAnswer(payload.answer)) return jsonError("Answer does not match the review schema");
      const answer = payload.answer;
      const frozen = packageFor(answer.reviewId);
      if (!frozen || frozen.package_digest !== answer.packageDigest) return jsonError("Frozen review package identity mismatch");
      const currentIndex = Math.max(0, Math.min(30, Number(payload.currentIndex ?? 0)));
      const locale: Locale = payload.locale === "en" ? "en" : "zh";
      await db.prepare(
        `INSERT INTO review_answers
        (session_id, review_id, package_digest, option_a_scores, option_b_scores,
         preferred, confidence, notes, is_final, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(session_id, review_id) DO UPDATE SET
          option_a_scores = excluded.option_a_scores,
          option_b_scores = excluded.option_b_scores,
          preferred = excluded.preferred,
          confidence = excluded.confidence,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        WHERE review_answers.is_final = 0`,
      ).bind(
        session.id, answer.reviewId, answer.packageDigest, JSON.stringify(answer.optionA),
        JSON.stringify(answer.optionB), answer.preferred, answer.confidence, answer.notes.trim(), now,
      ).run();
      await db.prepare("UPDATE review_sessions SET locale = ?, current_index = ?, updated_at = ? WHERE id = ?")
        .bind(locale, currentIndex, now, session.id).run();
      return Response.json({ ok: true, savedAt: now });
    }

    if (action === "submit") {
      const result = await db.prepare("SELECT * FROM review_answers WHERE session_id = ?").bind(session.id).all<D1Row>();
      const answers = result.results.map(deserializeAnswer);
      const expected = new Map(reviewBundle.packages.map((item) => [item.review_id, item.package_digest]));
      const complete = answers.length === reviewBundle.package_count &&
        answers.every((answer) => expected.get(answer.reviewId) === answer.packageDigest && answerComplete(answer));
      if (!complete) return jsonError("All 30 frozen review packages must be complete", 409);
      await db.batch([
        db.prepare("UPDATE review_answers SET is_final = 1, updated_at = ? WHERE session_id = ?").bind(now, session.id),
        db.prepare("UPDATE review_sessions SET status = 'SUBMITTED', current_index = 30, submitted_at = ?, updated_at = ? WHERE id = ? AND status = 'DRAFT'").bind(now, now, session.id),
      ]);
      return Response.json({ ok: true, submittedAt: now });
    }

    return jsonError("Unsupported action");
  } catch (error) {
    if (error instanceof Response) return error;
    return jsonError(error instanceof Error ? error.message : "Unable to update review", 500);
  }
}
