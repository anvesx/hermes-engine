// "Sign in with Google" (OpenID Connect, authorization code + PKCE). Only accounts Google marks as verified, on an
// allowed Workspace domain (ALLOWED_DOMAINS), get in. Needs GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET; the OAuth
// client's authorized redirect URI is <PUBLIC_URL>/api/auth/google/callback. GOOGLE_AUTH_URL, GOOGLE_TOKEN_URL and
// GOOGLE_ISSUER exist only so tests can point at a fake provider.
import { createHash, randomBytes } from "node:crypto";
import { publicBase } from "./board";

export const OAUTH_COOKIE = "tm_oauth";
export const OAUTH_TTL_S = 600;

const AUTH_URL = () => process.env.GOOGLE_AUTH_URL || "https://accounts.google.com/o/oauth2/v2/auth";
const TOKEN_URL = () => process.env.GOOGLE_TOKEN_URL || "https://oauth2.googleapis.com/token";
const ISSUERS = () => (process.env.GOOGLE_ISSUER ? [process.env.GOOGLE_ISSUER] : ["https://accounts.google.com", "accounts.google.com"]);

export const googleEnabled = () => !!(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
export const redirectUri = () => `${publicBase()}/api/auth/google/callback`;
export const allowedDomains = () =>
  (process.env.ALLOWED_DOMAINS || "devxlabs.ai").split(",").map((d) => d.trim().toLowerCase()).filter(Boolean);

const b64url = (b: Buffer) => b.toString("base64url");
export const randomId = (bytes = 24) => b64url(randomBytes(bytes));

/** What the browser carries between /api/auth/google and the callback (httpOnly cookie, 10 minutes). */
export type OAuthState = { state: string; verifier: string; nonce: string; cliPort?: number; cliState?: string };

export function newOAuthState(cli?: { port: number; state: string }): OAuthState {
  return { state: randomId(), verifier: randomId(32), nonce: randomId(), cliPort: cli?.port, cliState: cli?.state };
}

export const encodeState = (s: OAuthState) => b64url(Buffer.from(JSON.stringify(s)));
export function decodeState(raw: string | undefined): OAuthState | null {
  try {
    const s = JSON.parse(Buffer.from(raw || "", "base64url").toString());
    return typeof s.state === "string" && typeof s.verifier === "string" && typeof s.nonce === "string" ? s : null;
  } catch {
    return null;
  }
}

export function authorizeUrl(s: OAuthState) {
  const u = new URL(AUTH_URL());
  u.search = new URLSearchParams({
    client_id: process.env.GOOGLE_CLIENT_ID!, redirect_uri: redirectUri(), response_type: "code",
    scope: "openid email profile", state: s.state, nonce: s.nonce, prompt: "select_account",
    hd: allowedDomains()[0], code_challenge: b64url(createHash("sha256").update(s.verifier).digest()),
    code_challenge_method: "S256",
  }).toString();
  return u.toString();
}

export type GoogleUser = { email: string; name: string };

/** Exchanges the code for an ID token and checks it. The ID token comes straight from Google's token endpoint over
 *  TLS, which OpenID Connect accepts in place of checking its signature; issuer, audience, expiry, nonce, verified
 *  email and Workspace domain are still checked. Returns why it failed instead of throwing. */
export async function exchangeCode(code: string, s: OAuthState): Promise<GoogleUser | { error: string }> {
  let r: Response;
  try {
    r = await fetch(TOKEN_URL(), {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code, client_id: process.env.GOOGLE_CLIENT_ID!, client_secret: process.env.GOOGLE_CLIENT_SECRET!,
        redirect_uri: redirectUri(), grant_type: "authorization_code", code_verifier: s.verifier,
      }),
    });
  } catch {
    return { error: "failed" };
  }
  if (!r.ok) return { error: "failed" };
  const body = (await r.json().catch(() => ({}))) as { id_token?: string };
  let c: Record<string, unknown>;
  try {
    c = JSON.parse(Buffer.from(String(body.id_token).split(".")[1], "base64url").toString());
  } catch {
    return { error: "failed" };
  }
  if (!ISSUERS().includes(String(c.iss)) || c.aud !== process.env.GOOGLE_CLIENT_ID || c.nonce !== s.nonce
      || typeof c.exp !== "number" || c.exp < Date.now() / 1000) return { error: "failed" };
  const email = String(c.email || "").toLowerCase();
  const hd = String(c.hd || "").toLowerCase();
  if (c.email_verified !== true || !hd || !allowedDomains().includes(hd) || email.split("@")[1] !== hd)
    return { error: "domain" };
  return { email, name: String(c.name || "").trim().replace(/\s+/g, " ").slice(0, 40) };
}
