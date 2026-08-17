import { env } from "cloudflare:workers";

const COOKIE_NAME = "glap_review_session";
const SESSION_SECONDS = 8 * 60 * 60;
const LEGACY_REVIEWER_ID = "reviewer-ops-01";
const PBKDF2_ITERATIONS = 100000;
const ADDITIONAL_ACCOUNT_KEYS = [
  "REVIEWER_ACCOUNT_02_JSON",
  "REVIEWER_ACCOUNT_03_JSON",
  "REVIEWER_ACCOUNT_04_JSON",
  "REVIEWER_ACCOUNT_05_JSON",
  "REVIEWER_ACCOUNT_06_JSON",
] as const;

type RuntimeConfig = {
  REVIEW_LOGIN_USERNAME?: string;
  REVIEW_PASSWORD_SALT?: string;
  REVIEW_PASSWORD_HASH?: string;
  REVIEW_PASSWORD_ITERATIONS?: string;
  REVIEW_SESSION_SECRET?: string;
} & Partial<Record<(typeof ADDITIONAL_ACCOUNT_KEYS)[number], string>>;

type ReviewerAccount = {
  userId: string;
  username: string;
  passwordSalt: string;
  passwordHash: string;
  passwordIterations: number;
};

export type ReviewerIdentity = { userId: string };

function configuredAccount(value: unknown, source: string): ReviewerAccount {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Reviewer account ${source} is not configured correctly`);
  }
  const item = value as Record<string, unknown>;
  const userId = typeof item.userId === "string" ? item.userId.trim() : "";
  const username = typeof item.username === "string" ? item.username.trim() : "";
  const passwordSalt = typeof item.passwordSalt === "string" ? item.passwordSalt.trim() : "";
  const passwordHash = typeof item.passwordHash === "string" ? item.passwordHash.trim() : "";
  const passwordIterations = Number(item.passwordIterations ?? PBKDF2_ITERATIONS);
  if (
    !/^reviewer-[a-z0-9][a-z0-9-]{2,63}$/u.test(userId) ||
    !username || username.length > 80 ||
    !/^[A-Za-z0-9_-]+$/u.test(passwordSalt) ||
    !/^[A-Za-z0-9_-]+$/u.test(passwordHash) ||
    decodeBase64Url(passwordSalt).length < 16 ||
    decodeBase64Url(passwordHash).length !== 32 ||
    passwordIterations !== PBKDF2_ITERATIONS
  ) {
    throw new Error(`Reviewer account ${source} is not configured correctly`);
  }
  return { userId, username, passwordSalt, passwordHash, passwordIterations };
}

function config() {
  const runtime = env as unknown as RuntimeConfig;
  const sessionSecret = runtime.REVIEW_SESSION_SECRET?.trim();
  const accounts: ReviewerAccount[] = [];
  const legacy = {
    username: runtime.REVIEW_LOGIN_USERNAME?.trim() ?? "",
    passwordSalt: runtime.REVIEW_PASSWORD_SALT?.trim() ?? "",
    passwordHash: runtime.REVIEW_PASSWORD_HASH?.trim() ?? "",
  };
  if (Object.values(legacy).some(Boolean)) {
    accounts.push(configuredAccount({
      userId: LEGACY_REVIEWER_ID,
      ...legacy,
      passwordIterations: Number(runtime.REVIEW_PASSWORD_ITERATIONS ?? String(PBKDF2_ITERATIONS)),
    }, "legacy"));
  }
  for (const key of ADDITIONAL_ACCOUNT_KEYS) {
    const raw = runtime[key]?.trim();
    if (!raw) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error(`Reviewer account ${key} is not configured correctly`);
    }
    accounts.push(configuredAccount(parsed, key));
  }
  if (!sessionSecret || accounts.length === 0) {
    throw new Error("Reviewer authentication is not configured");
  }
  const userIds = new Set(accounts.map((account) => account.userId));
  const usernames = new Set(accounts.map((account) => account.username.toLowerCase()));
  if (userIds.size !== accounts.length || usernames.size !== accounts.length) {
    throw new Error("Reviewer authentication contains duplicate accounts");
  }
  return { accounts, sessionSecret };
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
  const account = current.accounts.find(
    (candidate) => candidate.username.toLowerCase() === username.trim().toLowerCase(),
  );
  if (!account || !password || password.length > 128) return null;
  const passwordKey = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const actual = new Uint8Array(await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt: decodeBase64Url(account.passwordSalt),
      iterations: account.passwordIterations,
    },
    passwordKey,
    256,
  ));
  return constantTimeEqual(actual, decodeBase64Url(account.passwordHash))
    ? { userId: account.userId }
    : null;
}

export async function createSessionCookie(request: Request, reviewer: ReviewerIdentity) {
  const now = Math.floor(Date.now() / 1000);
  const payload = encodeBase64Url(new TextEncoder().encode(JSON.stringify({ sub: reviewer.userId, iat: now, exp: now + SESSION_SECONDS })));
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
    const account = config().accounts.find((candidate) => candidate.userId === claims.sub);
    if (!account || !claims.exp || claims.exp <= Math.floor(Date.now() / 1000)) return null;
    return { userId: account.userId };
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
