import { findOrCreateUser, newToken, normaliseEmail, sha256 } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { q } from "@/lib/db";
import { BodyError, fail, ok, readJson } from "@/lib/http";

type Body = { email?: unknown; display_name?: unknown };

/** CLI: joins with the email and name from the user's git config. No email code; see the README's Privacy note. */
export async function POST(req: Request) {
  let body: Body;
  try {
    body = (await readJson(req, 1_000)) as Body;
  } catch (e) {
    return e instanceof BodyError ? fail(e.message, e.status) : fail("bad request");
  }
  const email = normaliseEmail(body?.email);
  if (!email) return fail("use your work email", 400);
  // An existing user keeps the name they chose; git's name is only used for new users.
  const user = await findOrCreateUser(email, body.display_name, false);
  const token = newToken();
  await q("INSERT INTO tokens (token_hash, user_id, kind) VALUES ($1, $2, 'cli')", [sha256(token), user.id]);
  return ok({ token, handle: user.handle, display_name: user.display_name, profile_url: `${publicBase()}/u/${user.handle}` });
}
