import { env } from "cloudflare:workers";

const COOKIE_NAME = "glap_review_session";
const SESSION_SECONDS = 8 * 60 * 60;
const REVIEWER_ID = "reviewer-ops-01";
const PBKDF2_ITERATIONS = 100000;

type RuntimeConfig = {
  REVIEW_LOGIN_USERNAME?: string;
  REVIEW_PASSWORD_SALT?: string;
  REVIEW_PASSWORD_HASH?: string;
  REVIEW_PASSWORD_ITERATIONS?: string;
  REVIEW_SESSION_SECRET?: string;
};

export type ReviewerIdentity = { userId: string; displayName: string };

function config() {
  const runtime = env as unknown as RuntimeConfig;
  const username = runtime.REVIEW_LOGIN_USERNAME?.trim();
  const salt = runtime.REVIEW_PASSWORD_SALT?.trim();
  const passwordHash = runtime.REVIEW_PASSWORD_HASH?.trim();
  const sessionSecret = runtime.REVIEW_SESSION_SECRET?.trim();
  const iterations = Number(runtime.REVIEW_PASSWORD_ITERATIONS ?? String(PBKDF2_ITERATIONS));
  if (!username || !salt || !passwordHash || !sessionSecret || iterations !== PBKDF2_ITERATIONS) {
    throw new Error("Reviewer authentication is not configured");
  }
  return { username, salt, passwordHash, sessionSecret, iterations };
}

function encodeBase64Url(bytes: Uint8Array) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

function decodeBase64Url(value: string) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array) {
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left[index] ?? 0) ^ (right[index] ?? 0);
  }
  return difference === 0;
}

async function hmac(value: string) {
  const { sessionSecret } = config();
  const key = await crypto.subtle.importKey(
    "raw",
    decodeBase64Url(sessionSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
}

export async function verifyCredentials(username: string, password: string) {
  const current = config();
  if (username.trim().toLowerCase() !== current.username.toLowerCase()) return false;
  if (!password || password.length > 128) return false;
  const passwordKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const actual = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: decodeBase64Url(current.salt), iterations: current.iterations },
    passwordKey,
    256,
  ));
  return constantTimeEqual(actual, decodeBase64Url(current.passwordHash));
}

export async function createSessionCookie(request: Request) {
  const now = Math.floor(Date.now() / 1000);
  const payload = encodeBase64Url(new TextEncoder().encode(JSON.stringify({ sub: REVIEWER_ID, iat: now, exp: now + SESSION_SECONDS })));
  const signature = encodeBase64Url(await hmac(payload));
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `${COOKIE_NAME}=${payload}.${signature}; Path=/; HttpOnly${secure}; SameSite=Strict; Max-Age=${SESSION_SECONDS}`;
}

export function clearSessionCookie(request: Request) {
  const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
  return `${COOKIE_NAME}=; Path=/; HttpOnly${secure}; SameSite=Strict; Max-Age=0`;
}

function cookieValue(request: Request) {
  const raw = request.headers.get("cookie") ?? "";
  for (const part of raw.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === COOKIE_NAME) return value.join("=");
  }
  return null;
}

export async function getReviewer(request: Request): Promise<ReviewerIdentity | null> {
  try {
    const token = cookieValue(request);
    if (!token) return null;
    const [payload, signature, extra] = token.split(".");
    if (!payload || !signature || extra) return null;
    const expected = await hmac(payload);
    if (!constantTimeEqual(expected, decodeBase64Url(signature))) return null;
    const claims = JSON.parse(new TextDecoder().decode(decodeBase64Url(payload))) as { sub?: string; exp?: number };
    if (claims.sub !== REVIEWER_ID || !claims.exp || claims.exp <= Math.floor(Date.now() / 1000)) return null;
    return { userId: REVIEWER_ID, displayName: "Ming" };
  } catch {
    return null;
  }
}

export async function requireReviewer(request: Request): Promise<ReviewerIdentity> {
  const reviewer = await getReviewer(request);
  if (!reviewer) throw Response.json({ error: "Authentication required" }, { status: 401 });
  return reviewer;
}

export async function authAttemptKey(request: Request, username: string) {
  const forwarded = request.headers.get("cf-connecting-ip") ?? request.headers.get("x-forwarded-for")?.split(",")[0] ?? "unknown";
  return encodeBase64Url(await hmac(`${username.trim().toLowerCase()}|${forwarded.trim()}`));
}

export function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}
