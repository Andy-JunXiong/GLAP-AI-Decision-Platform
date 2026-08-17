import { authAttemptKey, createSessionCookie, sameOrigin, verifyCredentials } from "../../../account-auth";
import { getD1 } from "@/db/runtime";

const WINDOW_MS = 15 * 60 * 1000;
const LOCK_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;

type Attempt = { failed_count: number; window_started_at: string; locked_until: string | null };

export async function POST(request: Request) {
  if (!sameOrigin(request)) return Response.json({ error: "Request origin rejected" }, { status: 403 });
  let body: { username?: string; password?: string };
  try {
    body = await request.json() as { username?: string; password?: string };
  } catch {
    return Response.json({ error: "Invalid request" }, { status: 400 });
  }
  const username = body.username?.trim() ?? "";
  const password = body.password ?? "";
  if (!username || username.length > 80 || !password || password.length > 128) {
    return Response.json({ error: "Invalid username or password" }, { status: 401 });
  }

  const db = getD1();
  const attemptKey = await authAttemptKey(request, username);
  const now = new Date();
  const prior = await db.prepare("SELECT failed_count, window_started_at, locked_until FROM login_attempts WHERE attempt_key = ?")
    .bind(attemptKey).first<Attempt>();
  if (prior?.locked_until && new Date(prior.locked_until) > now) {
    return Response.json({ error: "Too many attempts. Try again later." }, { status: 429, headers: { "retry-after": "900" } });
  }

  const reviewer = await verifyCredentials(username, password);
  if (!reviewer) {
    const windowExpired = !prior || now.getTime() - new Date(prior.window_started_at).getTime() > WINDOW_MS;
    const failedCount = windowExpired ? 1 : prior.failed_count + 1;
    const windowStartedAt = windowExpired ? now.toISOString() : prior.window_started_at;
    const lockedUntil = failedCount >= MAX_FAILURES ? new Date(now.getTime() + LOCK_MS).toISOString() : null;
    await db.prepare(
      `INSERT INTO login_attempts (attempt_key, failed_count, window_started_at, locked_until, updated_at)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(attempt_key) DO UPDATE SET
         failed_count = excluded.failed_count,
         window_started_at = excluded.window_started_at,
         locked_until = excluded.locked_until,
         updated_at = excluded.updated_at`,
    ).bind(attemptKey, failedCount, windowStartedAt, lockedUntil, now.toISOString()).run();
    return Response.json({ error: "Invalid username or password" }, { status: 401 });
  }

  await db.prepare("DELETE FROM login_attempts WHERE attempt_key = ?").bind(attemptKey).run();
  return Response.json(
    { ok: true },
    { headers: { "set-cookie": await createSessionCookie(request, reviewer), "cache-control": "no-store" } },
  );
}
