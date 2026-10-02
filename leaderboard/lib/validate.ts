import { isWeekKey, shiftWeek, weekKey } from "./weeks";

export type Week = {
  week: string;
  tokens: number;
  cost_usd: number;
  active_hours: number;
  active_days: number;
  sessions: number;
  hook_sessions: number;
  tasks: number;
  tagged_tasks: number;
  rated_tasks: number;
  top_category: string | null;
  model_cost: Record<string, number>;
  leak_share: Record<string, number>;
  waste_index: number;
};

export type Lifetime = Omit<Week, "week"> & { first_day: string | null; longest_streak_days: number };
export type Payload = { client: string; lifetime: Lifetime; weeks: Week[] };

const FAMILIES = ["fable", "opus", "sonnet", "haiku", "other"];
// per-week ceilings; lifetime numbers are allowed 60x (about a year of weeks)
const LIMITS: Record<string, number> = {
  tokens: 1e12, cost_usd: 1e6, active_hours: 168, active_days: 7, sessions: 10_000, hook_sessions: 10_000,
  tasks: 50_000, tagged_tasks: 50_000, rated_tasks: 50_000, waste_index: 50, longest_streak_days: 3660,
};

class Invalid extends Error {}

function num(v: unknown, field: string, scale: number): number {
  const max = (LIMITS[field] ?? 1e12) * scale;
  if (typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > max) throw new Invalid(`bad ${field}`);
  return v;
}

function shareMap(v: unknown): Record<string, number> {
  if (!v || typeof v !== "object") return {};
  const out: Record<string, number> = {};
  for (const [k, x] of Object.entries(v)) {
    const n = Number(k);
    if (Number.isInteger(n) && n >= 1 && n <= 50 && typeof x === "number" && x >= 0 && x <= 5) out[String(n)] = x;
  }
  return out;
}

function costMap(v: unknown, scale: number): Record<string, number> {
  if (!v || typeof v !== "object") return {};
  const out: Record<string, number> = {};
  for (const [k, x] of Object.entries(v)) if (FAMILIES.includes(k)) out[k] = num(x, "cost_usd", scale);
  return out;
}

function block(raw: Record<string, unknown>, scale: number, where: string) {
  const cat = raw.top_category;
  let b;
  try {
    b = {
    tokens: Math.round(num(raw.tokens, "tokens", scale)),
    cost_usd: num(raw.cost_usd, "cost_usd", scale),
    active_hours: num(raw.active_hours, "active_hours", scale),
    active_days: Math.round(num(raw.active_days, "active_days", scale)),
    sessions: Math.round(num(raw.sessions, "sessions", scale)),
    hook_sessions: Math.round(num(raw.hook_sessions, "hook_sessions", scale)),
    tasks: Math.round(num(raw.tasks, "tasks", scale)),
    tagged_tasks: Math.round(num(raw.tagged_tasks, "tagged_tasks", scale)),
    rated_tasks: Math.round(num(raw.rated_tasks, "rated_tasks", scale)),
    top_category: typeof cat === "string" && /^[a-z][\w-]{0,39}$/.test(cat) ? cat : null,
    model_cost: costMap(raw.model_cost, scale),
    leak_share: shareMap(raw.leak_share),
    waste_index: num(raw.waste_index ?? 0, "waste_index", 1),
    };
  } catch (e) {
    throw e instanceof Invalid ? new Invalid(`${where}: ${e.message}`) : e;
  }
  // counts that can't exceed each other; clients report their own numbers, so keep them plausible
  if (b.hook_sessions > b.sessions || b.tagged_tasks > b.tasks || b.rated_tasks > 3 * b.tasks + 3)
    throw new Invalid(`${where}: inconsistent counts`);
  return b;
}

/** Keeps only known fields with sane values; throws on anything malformed. */
export function parsePayload(raw: unknown): Payload {
  try {
    if (!raw || typeof raw !== "object") throw new Invalid("payload must be an object");
    const p = raw as Record<string, unknown>;
    if (p.schema !== 1) throw new Invalid("unsupported schema; update the plugin");
    if (!Array.isArray(p.weeks) || p.weeks.length > 60) throw new Invalid("weeks must be a list of at most 60");
    const latest = shiftWeek(weekKey(new Date()), 1);   // clients a timezone ahead may be in next week
    const seen = new Set<string>();
    const weeks = p.weeks.map((w) => {
      if (!w || typeof w !== "object") throw new Invalid("bad week");
      const r = w as Record<string, unknown>;
      if (!isWeekKey(r.week) || r.week > latest || seen.has(r.week)) throw new Invalid("bad week key");
      seen.add(r.week);
      return { week: r.week, ...block(r, 1, `week ${r.week}`) };
    });
    const life = (p.lifetime || {}) as Record<string, unknown>;
    const first = typeof life.first_day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(life.first_day) ? life.first_day : null;
    const lifetime = { ...block(life, 60, "lifetime"), first_day: first,
                       longest_streak_days: Math.round(num(life.longest_streak_days ?? 0, "longest_streak_days", 1)) };
    const client = typeof p.client === "string" ? p.client.slice(0, 40) : "unknown";
    return { client, lifetime, weeks };
  } catch (e) {
    if (e instanceof Invalid) throw new PayloadError(e.message);
    throw e;
  }
}

export class PayloadError extends Error {}
