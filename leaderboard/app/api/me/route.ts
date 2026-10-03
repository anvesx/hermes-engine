import { currentUser } from "@/lib/auth";
import { loadPlayers, publicBase, rank } from "@/lib/board";
import { q } from "@/lib/db";
import { BodyError, fail, ok, readJson } from "@/lib/http";
import { weekKey } from "@/lib/weeks";

const CARD_FIELDS = ["name", "level", "badges", "streak", "tokens", "hours", "spend"];

export async function GET() {
  const user = await currentUser();
  if (!user) return fail("not signed in", 401);
  const players = await loadPlayers();
  const me = players.find((p) => p.user.id === user.id)!;
  const week = rank(players, "week");
  const p = me.profile;
  return ok({
    display_name: user.display_name, email: user.email, handle: user.handle,
    points: p.points, level: p.level, streak_weeks: p.streak_weeks, best_streak_weeks: p.best_streak_weeks,
    rank: week.find((r) => r.handle === user.handle)?.rank ?? null, players: week.length,
    volume: p.volume, badges: p.badges, next_badges: p.next_badges, recent: p.scores.slice(-4),
    card_fields: user.card_fields, profile_url: `${publicBase()}/u/${user.handle}`,
    last_sync_at: me.last_sync_at,
    this_week: (({ tokens, cost_usd, active_hours, token_split }) => ({ tokens, cost_usd, active_hours, token_split }))(
      me.weeks.find((w) => w.week === weekKey(new Date())) ?? { tokens: 0, cost_usd: 0, active_hours: 0, token_split: {} }),
  });
}

export async function PATCH(req: Request) {
  const user = await currentUser();
  if (!user) return fail("not signed in", 401);
  let body: { card_fields?: Record<string, unknown> };
  try {
    body = (await readJson(req, 2_000)) as typeof body;
  } catch (e) {
    return e instanceof BodyError ? fail(e.message, e.status) : fail("bad request");
  }
  const fields = Object.fromEntries(CARD_FIELDS.map((f) => [f, body?.card_fields?.[f] !== false]));
  await q("UPDATE users SET card_fields = $1 WHERE id = $2", [fields, user.id]);
  return ok({ card_fields: fields });
}

export async function DELETE() {
  const user = await currentUser();
  if (!user) return fail("not signed in", 401);
  // tokens and weekly_stats cascade
  await q("DELETE FROM users WHERE id = $1", [user.id]);
  await q("DELETE FROM login_codes WHERE email = $1", [user.email]);
  return ok({ deleted: true });
}
