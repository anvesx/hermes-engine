import { NextResponse } from "next/server";
import { publicBase } from "@/lib/board";
import { OAUTH_COOKIE, OAUTH_TTL_S, authorizeUrl, encodeState, googleEnabled, newOAuthState } from "@/lib/google";

/** Starts "Sign in with Google". The plugin adds ?cli_port=&cli_state= so the result is handed back to a listener on
 *  the user's own machine (127.0.0.1), never to whoever made the link. */
export async function GET(req: Request) {
  const base = publicBase();
  if (!googleEnabled()) return NextResponse.redirect(`${base}/login?google=off`);
  const p = new URL(req.url).searchParams;
  const port = Number(p.get("cli_port"));
  const cliState = p.get("cli_state") || "";
  const cli = p.has("cli_port")
    ? (Number.isInteger(port) && port >= 1024 && port <= 65535 && /^[A-Za-z0-9_-]{16,128}$/.test(cliState) ? { port, state: cliState } : null)
    : undefined;
  if (cli === null) return NextResponse.redirect(`${base}/login?google=failed`);
  const s = newOAuthState(cli);
  const res = NextResponse.redirect(authorizeUrl(s));
  res.cookies.set(OAUTH_COOKIE, encodeState(s), {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/api/auth/google", maxAge: OAUTH_TTL_S,
  });
  return res;
}
