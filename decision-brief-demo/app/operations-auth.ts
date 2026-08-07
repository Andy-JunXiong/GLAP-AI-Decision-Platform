const accessTokenKey = "glap.internal.operations.access_token";
const verifierKey = "glap.internal.operations.pkce_verifier";
const stateKey = "glap.internal.operations.oauth_state";

function cognitoDomain() {
  return (process.env.NEXT_PUBLIC_GLAP_COGNITO_DOMAIN ?? "").replace(/\/$/, "");
}

function clientId() {
  return process.env.NEXT_PUBLIC_GLAP_COGNITO_CLIENT_ID ?? "";
}

function expectedOrigin() {
  return (process.env.NEXT_PUBLIC_GLAP_INTERNAL_ORIGIN ?? "").replace(/\/$/, "");
}

export function internalAuthenticationEnabled() {
  return cognitoDomain().startsWith("https://") && clientId().length > 3;
}

function redirectUri() {
  if (typeof window === "undefined") return "";
  const origin = window.location.origin;
  if (expectedOrigin() && origin !== expectedOrigin()) {
    throw new Error("This build is not running on its approved internal origin");
  }
  return `${origin}/`;
}

function base64Url(bytes: Uint8Array) {
  let binary = "";
  bytes.forEach((value) => { binary += String.fromCharCode(value); });
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomValue(size = 32) {
  const bytes = new Uint8Array(size);
  window.crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

async function challengeFor(verifier: string) {
  const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

export async function signInOperations() {
  if (!internalAuthenticationEnabled()) throw new Error("Internal identity is not configured");
  const verifier = randomValue(48);
  const state = randomValue();
  window.sessionStorage.setItem(verifierKey, verifier);
  window.sessionStorage.setItem(stateKey, state);
  const params = new URLSearchParams({
    client_id: clientId(), response_type: "code", scope: "openid email profile",
    redirect_uri: redirectUri(), state, code_challenge_method: "S256",
    code_challenge: await challengeFor(verifier),
  });
  window.location.assign(`${cognitoDomain()}/oauth2/authorize?${params}`);
}

export async function finishOperationsSignIn() {
  if (typeof window === "undefined") return false;
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const returnedState = url.searchParams.get("state");
  if (!code) return false;
  const expectedState = window.sessionStorage.getItem(stateKey);
  const verifier = window.sessionStorage.getItem(verifierKey);
  if (!returnedState || !expectedState || returnedState !== expectedState || !verifier) {
    throw new Error("The sign-in response could not be verified");
  }
  const response = await fetch(`${cognitoDomain()}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code", client_id: clientId(), code,
      redirect_uri: redirectUri(), code_verifier: verifier,
    }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || typeof body.access_token !== "string") {
    throw new Error("The internal sign-in exchange failed");
  }
  window.sessionStorage.setItem(accessTokenKey, body.access_token);
  window.sessionStorage.removeItem(verifierKey);
  window.sessionStorage.removeItem(stateKey);
  url.searchParams.delete("code");
  url.searchParams.delete("state");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}

export function operationsSignedIn() {
  return typeof window !== "undefined" && Boolean(window.sessionStorage.getItem(accessTokenKey));
}

export function signOutOperations() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(accessTokenKey);
  window.sessionStorage.removeItem(verifierKey);
  window.sessionStorage.removeItem(stateKey);
  if (!internalAuthenticationEnabled()) return;
  const params = new URLSearchParams({ client_id: clientId(), logout_uri: redirectUri() });
  window.location.assign(`${cognitoDomain()}/logout?${params}`);
}
