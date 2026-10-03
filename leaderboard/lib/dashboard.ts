import { type Period, companyStats, loadPlayers, periodWeeks, rank } from "./board";
import categories from "./categories.json";
import { type Lifetime, TOKEN_KINDS, type TokenKind, type Week } from "./validate";
import { shiftWeek, weekKey } from "./weeks";

const CATS = categories as Record<string, { name: string; group: string; review: boolean }>;
export const TREND_WEEKS = 12;
export const DAILY = 30;

export type TrendWeek = {
  week: string; tokens: number; cost_usd: number; active_hours: number; active_days: number;
  waste_index: number | null; participation: number; improvement: number;
};

/** Everything the signed-in owner of /u/<handle> sees about themselves, plus where they stand. */
export async function dashboardFor(userId: string, period: Period, now = new Date()) {
  const players = await loadPlayers(now);
  const me = players.find((p) => p.user.id === userId);
  if (!me) return null;
  const standing = (per: Period) => {
    const rows = rank(players, per, now);
    return { rows, rank: rows.find((r) => r.handle === me.user.handle)?.rank ?? null, of: rows.length };
  };
  const board = standing(period);
  const ranks = { week: period === "week" ? board : standing("week"),
                  month: period === "month" ? board : standing("month"),
                  all: period === "all" ? board : standing("all") };

  const byWeek = new Map(me.weeks.map((w) => [w.week, w]));
  const scores = new Map(me.profile.scores.map((s) => [s.week, s]));
  const cur = weekKey(now);
  const trend: TrendWeek[] = Array.from({ length: TREND_WEEKS }, (_, i) => shiftWeek(cur, i - TREND_WEEKS + 1)).map((k) => {
    const w = byWeek.get(k), s = scores.get(k);
    return {
      week: k, tokens: w?.tokens ?? 0, cost_usd: w?.cost_usd ?? 0, active_hours: w?.active_hours ?? 0,
      active_days: w?.active_days ?? 0, waste_index: w && w.active_days > 0 ? w.waste_index : null,
      participation: s?.participation ?? 0, improvement: s?.improvement ?? 0,
    };
  });

  const month = periodWeeks("month", now)!;
  const recent = me.weeks.filter((w) => month.has(w.week));
  const company = companyStats(players, month);
  const leaks = leakShares(recent)
    .map(([id, mine]) => ({ id, mine, company: company.leak[id] ?? 0, name: CATS[id]?.name ?? `Category ${id}`,
                            group: CATS[id]?.group ?? "", review: !!CATS[id]?.review }))
    .slice(0, 8);

  const life = me.user.lifetime as Lifetime | null;
  const totals = {
    ...me.profile.volume,
    active_days: Math.max(sum(me.weeks, (w) => w.active_days), life?.active_days ?? 0),
    tasks: Math.max(sum(me.weeks, (w) => w.tasks), life?.tasks ?? 0),
    tagged_tasks: Math.max(sum(me.weeks, (w) => w.tagged_tasks), life?.tagged_tasks ?? 0),
    rated_tasks: Math.max(sum(me.weeks, (w) => w.rated_tasks), life?.rated_tasks ?? 0),
    longest_streak_days: life?.longest_streak_days ?? 0,
    top_category: life?.top_category ?? null,
  };
  const models = Object.entries(life?.model_cost ?? {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const tokens = tokenUsage(me.user.days ?? [], recent, byWeek.get(cur) ?? null, now);

  return {
    player: me, profile: me.profile, period, board: board.rows, ranks, trend, leaks, models, totals, tokens,
    this_week: byWeek.get(cur) ?? null, last_week: byWeek.get(shiftWeek(cur, -1)) ?? null,
  };
}

export type Dashboard = NonNullable<Awaited<ReturnType<typeof dashboardFor>>>;

const sum = (ws: Week[], f: (w: Week) => number) => ws.reduce((a, w) => a + f(w), 0);

/** Spend-weighted share of spend per leak category over the given weeks, largest first. */
function leakShares(ws: Week[]): [string, number][] {
  const spend = sum(ws, (w) => w.cost_usd);
  if (!spend) return [];
  const out: Record<string, number> = {};
  for (const w of ws) for (const [k, v] of Object.entries(w.leak_share)) out[k] = (out[k] ?? 0) + v * w.cost_usd;
  return Object.entries(out).map(([k, v]) => [k, v / spend] as [string, number]).filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
}

type DayRow = { day: string; tokens: number; cost_usd: number; active_hours: number };

/** Token detail: the daily series, the split by type and by model, and the subagent share. */
function tokenUsage(days: DayRow[], recent: Week[], thisWeek: Week | null, now: Date) {
  const byDay = new Map(days.map((d) => [d.day, d]));
  // days are keyed by the user's local calendar: end the window on the later of today (UTC) and their latest day
  const latest = [...byDay.keys()].sort().pop();
  const end = new Date(Math.max(Date.parse(now.toISOString().slice(0, 10)), latest ? Date.parse(latest) : 0));
  const daily = Array.from({ length: DAILY }, (_, i) => {
    const d = new Date(end);
    d.setUTCDate(d.getUTCDate() - (DAILY - 1 - i));
    const key = d.toISOString().slice(0, 10);
    return { day: key, tokens: byDay.get(key)?.tokens ?? 0, cost_usd: byDay.get(key)?.cost_usd ?? 0 };
  });
  const active = daily.filter((d) => d.tokens > 0);
  const splitOf = (ws: Week[]) => Object.fromEntries(TOKEN_KINDS.map((k) => [k, sum(ws, (w) => w.token_split?.[k] ?? 0)])) as Record<TokenKind, number>;
  const modelsOf = (ws: Week[]) => {
    const out: Record<string, number> = {};
    for (const w of ws) for (const [m, n] of Object.entries(w.model_tokens ?? {})) out[m] = (out[m] ?? 0) + n;
    return Object.entries(out).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  };
  const recentTokens = sum(recent, (w) => w.tokens);
  return {
    daily,
    today: daily[daily.length - 1].tokens,
    last30: daily.reduce((a, d) => a + d.tokens, 0),
    per_active_day: active.length ? active.reduce((a, d) => a + d.tokens, 0) / active.length : 0,
    week_split: thisWeek ? splitOf([thisWeek]) : null,
    split: splitOf(recent),
    models: modelsOf(recent),
    agent_share: recentTokens ? sum(recent, (w) => w.agent_tokens ?? 0) / recentTokens : 0,
    has_detail: recent.some((w) => w.token_split && Object.keys(w.token_split).length > 0),
    has_daily: days.length > 0,
  };
}
