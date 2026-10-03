// Points, levels, streaks and badges, computed from stored weekly stats.
// Volume (tokens, spend, hours) is shown and earns cosmetic badges, but never points:
// otherwise the heaviest spenders would win a leaderboard meant to reduce waste.
import type { Lifetime, Week } from "./validate";
import { shiftWeek, weekKey } from "./weeks";

export const RULES = {
  synced: 10,                 // an active week, synced
  hooked: 10,                 // >= 80% of the week's sessions have hook data
  hookedShare: 0.8,
  perTagged: 2, taggedCap: 20,
  perRated: 3, ratedCap: 30,
  improvementCap: 50,         // 1 point per % below your own baseline waste index
  minActiveDays: 3,           // weeks lighter than this don't set or earn improvement
};

export const LEVELS = [
  [0, "Rookie"], [50, "Apprentice"], [150, "Practitioner"], [300, "Optimizer"], [500, "Specialist"],
  [800, "Expert"], [1200, "Master"], [1700, "Grandmaster"], [2300, "Legend"], [3000, "Mythic"],
] as const;

export type WeekScore = { week: string; participation: number; improvement: number; points: number };

export type Profile = {
  points: number;
  weekPoints: Record<string, number>;
  scores: WeekScore[];
  level: { level: number; title: string; points: number; next_at: number | null };
  streak_weeks: number;
  best_streak_weeks: number;
  baseline: number | null;
  volume: { tokens: number; cost_usd: number; active_hours: number; sessions: number };
  badges: { id: string; name: string; description: string }[];
  next_badges: { id: string; name: string; hint: string; progress: number }[];
};

const active = (w: Week) => w.sessions > 0;
const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

export function levelFor(points: number) {
  let i = 0;
  while (i + 1 < LEVELS.length && points >= LEVELS[i + 1][0]) i++;
  return { level: i + 1, title: LEVELS[i][1], points, next_at: i + 1 < LEVELS.length ? LEVELS[i + 1][0] : null };
}

/** Consecutive active weeks ending this week, or last week while this one has no activity yet. */
function streaks(weeks: Week[], now: Date) {
  const activeKeys = new Set(weeks.filter(active).map((w) => w.week));
  let k = weekKey(now);
  if (!activeKeys.has(k)) k = shiftWeek(k, -1);
  let current = 0;
  while (activeKeys.has(k)) {
    current++;
    k = shiftWeek(k, -1);
  }
  let best = 0, run = 0, prev: string | null = null;
  for (const key of [...activeKeys].sort()) {
    run = prev && shiftWeek(prev, 1) === key ? run + 1 : 1;
    best = Math.max(best, run);
    prev = key;
  }
  return { current, best };
}

type BadgeCtx = { weeks: Week[]; joined: Week[]; scores: WeekScore[]; p: Omit<Profile, "badges" | "next_badges">;
                  companyCat1: number | null };
type Badge = { id: string; name: string; description: string; progress: (c: BadgeCtx) => [number, number]; unit?: string };

const sum = (ws: Week[], f: (w: Week) => number) => ws.reduce((a, w) => a + f(w), 0);
const any = (ok: boolean): [number, number] => [ok ? 1 : 0, 1];

export const BADGES: Badge[] = [
  { id: "first_sync", name: "First Sync", description: "Joined the leaderboard", progress: () => [1, 1] },
  { id: "hooked", name: "Fully Hooked", description: "A week with hook data on 80%+ of sessions",
    progress: (c) => any(c.joined.some((w) => active(w) && w.hook_sessions >= RULES.hookedShare * w.sessions)) },
  { id: "tagger", name: "Tagger", description: "50 tasks tagged with [category]", unit: "tagged tasks",
    progress: (c) => [sum(c.weeks, (w) => w.tagged_tasks), 50] },
  { id: "rater", name: "Honest Rater", description: "25 tasks rated with `rate N`", unit: "rated tasks",
    progress: (c) => [sum(c.weeks, (w) => w.rated_tasks), 25] },
  { id: "plugger", name: "Leak Plugger", description: "A week 25%+ below your own baseline waste",
    progress: (c) => any(c.scores.some((s) => s.improvement >= 25)) },
  { id: "cache_keeper", name: "Cache Keeper", description: "An active week where expired cache cost under 2% of spend",
    progress: (c) => any(c.joined.some((w) => w.active_days >= RULES.minActiveDays && (w.leak_share["4"] ?? 1) < 0.02)) },
  { id: "lean_start", name: "Lean Start", description: "Starting context lighter than the company median for a week",
    progress: (c) => any(c.companyCat1 !== null &&
      c.joined.some((w) => w.active_days >= RULES.minActiveDays && (w.leak_share["1"] ?? 1) < c.companyCat1!)) },
  { id: "streak4", name: "On a Roll", description: "4-week activity streak", unit: "weeks",
    progress: (c) => [c.p.best_streak_weeks, 4] },
  { id: "streak12", name: "Unstoppable", description: "12-week activity streak", unit: "weeks",
    progress: (c) => [c.p.best_streak_weeks, 12] },
  // volume badges: cosmetic, no points
  { id: "tok100m", name: "100M Club", description: "100M tokens processed", unit: "tokens",
    progress: (c) => [c.p.volume.tokens, 1e8] },
  { id: "tok1b", name: "Billionaire", description: "1B tokens processed", unit: "tokens",
    progress: (c) => [c.p.volume.tokens, 1e9] },
  { id: "tok10b", name: "Token Titan", description: "10B tokens processed", unit: "tokens",
    progress: (c) => [c.p.volume.tokens, 1e10] },
  { id: "hours100", name: "Centurion", description: "100 active hours in Claude Code", unit: "hours",
    progress: (c) => [c.p.volume.active_hours, 100] },
  { id: "hours500", name: "Lifer", description: "500 active hours in Claude Code", unit: "hours",
    progress: (c) => [c.p.volume.active_hours, 500] },
];

const compact = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : `${Math.round(n)}`;

export function scoreUser(weeks: Week[], lifetime: Lifetime | null, joinedAt: Date, now: Date,
                          companyCat1: number | null): Profile {
  weeks = [...weeks].sort((a, b) => a.week.localeCompare(b.week));
  const joinWeek = weekKey(joinedAt);

  // baseline: the first two substantial weeks, usually from history synced on joining
  const substantial = weeks.filter((w) => w.active_days >= RULES.minActiveDays);
  const baseWeeks = substantial.slice(0, 2);
  const baseline = median(baseWeeks.map((w) => w.waste_index));
  const baseKeys = new Set(baseWeeks.map((w) => w.week));

  // points only for weeks from the join week on; earlier history only sets the baseline
  const joined = weeks.filter((w) => w.week >= joinWeek);
  const scores: WeekScore[] = joined.filter(active).map((w) => {
    let participation = RULES.synced;
    if (w.hook_sessions >= RULES.hookedShare * w.sessions) participation += RULES.hooked;
    participation += Math.min(RULES.taggedCap, w.tagged_tasks * RULES.perTagged);
    participation += Math.min(RULES.ratedCap, w.rated_tasks * RULES.perRated);
    let improvement = 0;
    if (baseline && !baseKeys.has(w.week) && w.active_days >= RULES.minActiveDays) {
      const pct = ((baseline - w.waste_index) / baseline) * 100;
      improvement = Math.round(Math.max(0, Math.min(RULES.improvementCap, pct)));
    }
    return { week: w.week, participation, improvement, points: participation + improvement };
  });
  const points = scores.reduce((a, s) => a + s.points, 0);
  const { current, best } = streaks(weeks, now);
  // local transcripts are deleted after ~30 days, so stored weeks can add up to more than the latest lifetime
  const volume = {
    tokens: Math.max(sum(weeks, (w) => w.tokens), lifetime?.tokens ?? 0),
    cost_usd: Math.round(Math.max(sum(weeks, (w) => w.cost_usd), lifetime?.cost_usd ?? 0) * 100) / 100,
    active_hours: Math.round(Math.max(sum(weeks, (w) => w.active_hours), lifetime?.active_hours ?? 0) * 10) / 10,
    sessions: Math.max(sum(weeks, (w) => w.sessions), lifetime?.sessions ?? 0),
  };
  const p = {
    points, scores, baseline, volume,
    weekPoints: Object.fromEntries(scores.map((s) => [s.week, s.points])),
    level: levelFor(points), streak_weeks: current, best_streak_weeks: best,
  };
  const ctx: BadgeCtx = { weeks, joined, scores, p, companyCat1 };
  const badges: Profile["badges"] = [];
  const next: Profile["next_badges"] = [];
  for (const b of BADGES) {
    const [have, need] = b.progress(ctx);
    if (have >= need) badges.push({ id: b.id, name: b.name, description: b.description });
    else next.push({ id: b.id, name: b.name, progress: Math.min(1, have / need),
                     hint: b.unit ? `${compact(have)}/${compact(need)} ${b.unit}` : b.description });
  }
  next.sort((a, b) => b.progress - a.progress);
  return { ...p, badges, next_badges: next };
}
