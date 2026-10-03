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
  // Count the attempt before checking it, in one statement: Postgres locks the row and re-checks
  // `attempts < max`, so parallel guesses can't get past MAX_CODE_ATTEMPTS.
  const row = await one<{ id: string; code_hash: string }>(
    `UPDATE login_codes SET attempts = attempts + 1
      WHERE id = (SELECT id FROM login_codes WHERE email = $1 AND NOT used AND expires_at > now()
                  ORDER BY created_at DESC LIMIT 1)
        AND attempts < $2
      RETURNING id, code_hash`,
    [email, MAX_CODE_ATTEMPTS],
  );
  if (!row) return fail("code expired; request a new one", 400);
  if (!sameHash(row.code_hash, sha256(code))) return fail("wrong code", 400);
  // spend the code exactly once, even if two correct guesses race
  if (!(await one("UPDATE login_codes SET used = true WHERE id = $1 AND NOT used RETURNING id", [row.id])))
    return fail("code expired; request a new one", 400);

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
