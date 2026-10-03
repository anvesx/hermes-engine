import { cookies } from "next/headers";
import { MAX_CODE_ATTEMPTS, SESSION_COOKIE, newToken, normaliseEmail, sameHash, sha256, slug } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { one, q } from "@/lib/db";
import { BodyError, fail, ok, readJson } from "@/lib/http";

type Body = { email?: unknown; code?: unknown; display_name?: unknown; web?: unknown };

export async function POST(req: Request) {
  let body: Body;
  try {
    body = (await readJson(req, 2_000)) as Body;
  } catch (e) {
    return e instanceof BodyError ? fail(e.message, e.status) : fail("bad request");
  }
  const email = normaliseEmail(body?.email);
  const code = typeof body?.code === "string" ? body.code.trim() : "";
  if (!email || !/^\d{6}$/.test(code)) return fail("enter the 6-digit code from the email");
  const row = await one<{ id: string; code_hash: string; attempts: number }>(
    `SELECT id, code_hash, attempts FROM login_codes
      WHERE email = $1 AND NOT used AND expires_at > now() ORDER BY created_at DESC LIMIT 1`,
    [email],
  );
  if (!row || row.attempts >= MAX_CODE_ATTEMPTS) return fail("code expired; request a new one", 400);
  if (!sameHash(row.code_hash, sha256(code))) {
    await q("UPDATE login_codes SET attempts = attempts + 1 WHERE id = $1", [row.id]);
    return fail("wrong code", 400);
  }
  await q("UPDATE login_codes SET used = true WHERE id = $1", [row.id]);

  let name = typeof body.display_name === "string" ? body.display_name.trim().replace(/\s+/g, " ").slice(0, 40) : "";
  if (/^[\d\s]+$/.test(name)) name = "";   // a pasted sign-in code, not a name
  let user = await one<{ id: string; handle: string; display_name: string }>("SELECT id, handle, display_name FROM users WHERE email = $1", [email]);
  if (!user) {
    user = await one("INSERT INTO users (email, display_name, handle) VALUES ($1, $2, $3) RETURNING id, handle, display_name",
                     [email, name || email.split("@")[0], slug(name || email.split("@")[0])]);
  } else if (name && name !== user.display_name) {
    await q("UPDATE users SET display_name = $1 WHERE id = $2", [name, user.id]);
  }
  const web = body.web === true;
  const token = newToken();
  await q("INSERT INTO tokens (token_hash, user_id, kind) VALUES ($1, $2, $3)", [sha256(token), user!.id, web ? "web" : "cli"]);
  if (web) {
    (await cookies()).set(SESSION_COOKIE, token, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 60 * 60 * 24 * 30,
    });
    return ok({ signed_in: true });
  }
  return ok({ token, handle: user!.handle, profile_url: `${publicBase()}/u/${user!.handle}` });
}
