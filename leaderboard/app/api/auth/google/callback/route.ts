import { NextResponse } from "next/server";
import { findOrCreateUser, issueToken, newToken, normaliseEmail, sameHash, sessionCookie, sha256 } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { q } from "@/lib/db";
import { OAUTH_COOKIE, decodeState, exchangeCode, googleEnabled } from "@/lib/google";

const CLI_CODE_TTL_S = 120;

/** Google sends the browser back here. The website gets a session cookie; the plugin gets a one-time code on its
 *  127.0.0.1 listener, which it exchanges for a CLI token (see ./exchange). */
export async function GET(req: Request) {
  const base = publicBase();
  const fail = (why: string) => {
    const res = NextResponse.redirect(`${base}/login?google=${why}`);
    res.cookies.delete({ name: OAUTH_COOKIE, path: "/api/auth/google" });
    return res;
  };
  if (!googleEnabled()) return fail("off");
  const p = new URL(req.url).searchParams;
  const cookie = req.headers.get("cookie")?.split(/;\s*/).find((c) => c.startsWith(`${OAUTH_COOKIE}=`))?.slice(OAUTH_COOKIE.length + 1);
  const s = decodeState(cookie);
  const state = p.get("state") || "";
  if (!s || !state || !sameHash(sha256(state), sha256(s.state))) return fail("failed");
  if (p.get("error")) return fail(p.get("error") === "access_denied" ? "cancelled" : "failed");
  const g = await exchangeCode(p.get("code") || "", s);
  if ("error" in g) return fail(g.error);
  const email = normaliseEmail(g.email);
  if (!email) return fail("domain");
  const user = await findOrCreateUser(email, g.name);

  let res: NextResponse;
  if (s.cliPort && s.cliState) {
    const code = newToken();
    await q("DELETE FROM cli_codes WHERE expires_at < now() OR used");
    await q("INSERT INTO cli_codes (code_hash, user_id, expires_at) VALUES ($1, $2, now() + make_interval(secs => $3))",
            [sha256(code), user.id, CLI_CODE_TTL_S]);
    const back = new URL(`http://127.0.0.1:${s.cliPort}/callback`);
    back.search = new URLSearchParams({ code, state: s.cliState }).toString();
    res = NextResponse.redirect(back.toString());
  } else {
    res = NextResponse.redirect(`${base}/`);
    res.cookies.set(...sessionCookie(await issueToken(user.id, "web")));
  }
  res.cookies.delete({ name: OAUTH_COOKIE, path: "/api/auth/google" });
  return res;
}
