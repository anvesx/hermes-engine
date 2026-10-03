import { NextResponse } from "next/server";
import { SESSION_COOKIE, currentUser, newToken, sha256 } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { one, q } from "@/lib/db";
import { fail, ok } from "@/lib/http";

const LINK_TTL_MIN = 5;

/** CLI: a single-use link that signs the browser in and lands on the user's dashboard. */
export async function POST() {
  const user = await currentUser();
  if (!user) return fail("not signed in", 401);
  const token = newToken();
  await q("DELETE FROM login_links WHERE expires_at < now() OR used");
  await q(
    "INSERT INTO login_links (token_hash, user_id, expires_at) VALUES ($1, $2, now() + make_interval(mins => $3))",
    [sha256(token), user.id, LINK_TTL_MIN],
  );
  return ok({ url: `${publicBase()}/api/auth/link?t=${token}`, dashboard_url: `${publicBase()}/u/${user.handle}`,
              expires_in_s: LINK_TTL_MIN * 60 });
}

/** Browser: spends the link, sets the session cookie and redirects to the dashboard. */
export async function GET(req: Request) {
  const t = new URL(req.url).searchParams.get("t") || "";
  const base = publicBase();
  const row = t && await one<{ user_id: string; handle: string }>(
    `UPDATE login_links l SET used = true FROM users u
      WHERE l.token_hash = $1 AND NOT l.used AND l.expires_at > now() AND u.id = l.user_id
      RETURNING l.user_id, u.handle`,
    [sha256(t)],
  );
  if (!row) return NextResponse.redirect(`${base}/login?expired=1`);
  const session = newToken();
  await q("INSERT INTO tokens (token_hash, user_id, kind) VALUES ($1, $2, 'web')", [sha256(session), row.user_id]);
  const res = NextResponse.redirect(`${base}/u/${row.handle}`);
  res.cookies.set(SESSION_COOKIE, session, {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
