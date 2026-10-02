import type { User } from "./auth";
import { q } from "./db";
import { type Profile, scoreUser } from "./score";
import type { Lifetime, Week } from "./validate";
import { shiftWeek, weekKey } from "./weeks";

export type Period = "week" | "month" | "all";
export type Player = { user: User; weeks: Week[]; profile: Profile; last_sync_at: Date | null };
export type Row = {
  rank: number; handle: string; display_name: string; level: number; title: string; points: number;
  streak_weeks: number; tokens: number; active_hours: number; cost_usd: number; badges: number;
};

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export function periodWeeks(period: Period, now = new Date()): Set<string> | null {
  if (period === "all") return null;
  const cur = weekKey(now);
  return new Set(period === "week" ? [cur] : [0, 1, 2, 3].map((n) => shiftWeek(cur, -n)));
}

/** Everyone's stats, scored. A company is small enough to score in memory on each request. */
export async function loadPlayers(now = new Date()): Promise<Player[]> {
  const users = await q<User & { last_sync_at: Date | null }>("SELECT * FROM users ORDER BY id");
  const rows = await q<{ user_id: string; payload: Week }>("SELECT user_id, payload FROM weekly_stats");
  const byUser = new Map<string, Week[]>();
  for (const r of rows) {
    const list = byUser.get(String(r.user_id)) ?? [];
    list.push(r.payload);
    byUser.set(String(r.user_id), list);
  }
  const recent = periodWeeks("month", now)!;
  const cat1 = median(rows.map((r) => r.payload).filter((w) => recent.has(w.week) && w.active_days >= 3)
                          .map((w) => w.leak_share["1"] ?? 0));
  return users.map((user) => {
    const weeks = byUser.get(String(user.id)) ?? [];
    return { user, weeks, last_sync_at: user.last_sync_at,
             profile: scoreUser(weeks, user.lifetime as Lifetime | null, new Date(user.created_at), now, cat1) };
  });
}

export function rank(players: Player[], period: Period, now = new Date()): Row[] {
  const keys = periodWeeks(period, now);
  const inPeriod = (week: string) => !keys || keys.has(week);
  const rows = players.map((pl) => {
    const ws = pl.weeks.filter((w) => inPeriod(w.week));
    const all = !keys;
    return {
      handle: pl.user.handle, display_name: pl.user.display_name,
      level: pl.profile.level.level, title: pl.profile.level.title,
      points: all ? pl.profile.points
        : pl.profile.scores.filter((s) => inPeriod(s.week)).reduce((a, s) => a + s.points, 0),
      streak_weeks: pl.profile.streak_weeks,
      tokens: all ? pl.profile.volume.tokens : ws.reduce((a, w) => a + w.tokens, 0),
      active_hours: Math.round((all ? pl.profile.volume.active_hours : ws.reduce((a, w) => a + w.active_hours, 0)) * 10) / 10,
      cost_usd: Math.round((all ? pl.profile.volume.cost_usd : ws.reduce((a, w) => a + w.cost_usd, 0)) * 100) / 100,
      badges: pl.profile.badges.length,
    };
  });
  rows.sort((a, b) => b.points - a.points || b.streak_weeks - a.streak_weeks || a.display_name.localeCompare(b.display_name));
  let prev: number | null = null, r = 0;
  return rows.map((row, i) => {
    if (row.points !== prev) r = i + 1;
    prev = row.points;
    return { rank: r, ...row };
  });
}

/** Company-wide view for /admin: spend-weighted leak shares and adoption, over the given weeks. */
export function companyStats(players: Player[], weeks: Set<string> | null) {
  const ws = players.flatMap((p) => p.weeks.filter((w) => !weeks || weeks.has(w.week)));
  const spend = ws.reduce((a, w) => a + w.cost_usd, 0);
  const leak: Record<string, number> = {};
  for (const w of ws) for (const [k, v] of Object.entries(w.leak_share)) leak[k] = (leak[k] ?? 0) + v * w.cost_usd;
  for (const k of Object.keys(leak)) leak[k] = spend ? leak[k] / spend : 0;
  const sessions = ws.reduce((a, w) => a + w.sessions, 0);
  return {
    players: players.length,
    active_players: new Set(players.filter((p) => p.weeks.some((w) => (!weeks || weeks.has(w.week)) && w.sessions)).map((p) => p.user.id)).size,
    spend: Math.round(spend * 100) / 100,
    tokens: ws.reduce((a, w) => a + w.tokens, 0),
    active_hours: Math.round(ws.reduce((a, w) => a + w.active_hours, 0) * 10) / 10,
    sessions,
    hook_coverage: sessions ? ws.reduce((a, w) => a + w.hook_sessions, 0) / sessions : 0,
    tagged_tasks: ws.reduce((a, w) => a + w.tagged_tasks, 0),
    rated_tasks: ws.reduce((a, w) => a + w.rated_tasks, 0),
    leak,
  };
}

export const publicBase = () => (process.env.PUBLIC_URL || "http://localhost:3000").replace(/\/$/, "");
