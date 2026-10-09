import { issueToken, sha256 } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { one } from "@/lib/db";
import { BodyError, fail, ok, readJson } from "@/lib/http";

/** The plugin trades the one-time code from the Google callback for a CLI token. Each code works once, for 2 minutes. */
export async function POST(req: Request) {
  let body: { code?: unknown };
  try {
    body = (await readJson(req, 1_000)) as typeof body;
  } catch (e) {
    return e instanceof BodyError ? fail(e.message, e.status) : fail("bad request");
  }
  const code = typeof body?.code === "string" ? body.code : "";
  if (!/^[A-Za-z0-9_-]{20,100}$/.test(code)) return fail("sign-in expired; run it again", 400);
  const row = await one<{ user_id: string; email: string; handle: string; display_name: string }>(
    `UPDATE cli_codes c SET used = true FROM users u
      WHERE c.code_hash = $1 AND NOT c.used AND c.expires_at > now() AND u.id = c.user_id
      RETURNING c.user_id, u.email, u.handle, u.display_name`,
    [sha256(code)],
  );
  if (!row) return fail("sign-in expired; run it again", 400);
  const token = await issueToken(row.user_id, "cli");
  return ok({ token, email: row.email, handle: row.handle, display_name: row.display_name,
              profile_url: `${publicBase()}/u/${row.handle}` });
}
