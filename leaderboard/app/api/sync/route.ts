import { currentUser } from "@/lib/auth";
import { pool } from "@/lib/db";
import { BodyError, fail, ok, readJson } from "@/lib/http";
import { PayloadError, parsePayload } from "@/lib/validate";

export async function POST(req: Request) {
  const user = await currentUser();
  if (!user) return fail("not signed in", 401);
  let payload;
  try {
    payload = parsePayload(await readJson(req, 256_000));
  } catch (e) {
    if (e instanceof BodyError) return fail(e.message, e.status);
    if (e instanceof PayloadError) return fail(e.message, 422);
    throw e;
  }
  const c = await pool.connect();
  try {
    await c.query("BEGIN");
    for (const w of payload.weeks) {
      await c.query(
        `INSERT INTO weekly_stats (user_id, week, payload) VALUES ($1, $2, $3)
         ON CONFLICT (user_id, week) DO UPDATE SET payload = EXCLUDED.payload, received_at = now()`,
        [user.id, w.week, w],
      );
    }
    // daily totals are a rolling window, replaced whole; older clients send none, so keep what's there
    await c.query(`UPDATE users SET lifetime = $1, client = $2, last_sync_at = now(),
                     days = CASE WHEN $4::jsonb = '[]'::jsonb THEN days ELSE $4::jsonb END WHERE id = $3`,
                  [payload.lifetime, payload.client, user.id, JSON.stringify(payload.days)]);
    await c.query("COMMIT");
  } catch (e) {
    await c.query("ROLLBACK");
    throw e;
  } finally {
    c.release();
  }
  return ok({ weeks: payload.weeks.length });
}
