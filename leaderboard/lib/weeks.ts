// ISO-8601 week keys like "2026-W40". Clients key weeks by their local calendar; the server uses UTC.

export function weekKey(d: Date): string {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);              // Thursday decides the ISO year
  const year = t.getUTCFullYear();
  const week = Math.ceil(((t.getTime() - Date.UTC(year, 0, 1)) / 86400000 + 1) / 7);
  return `${year}-W${String(week).padStart(2, "0")}`;
}

export function weekStart(key: string): Date {
  const [y, w] = key.split("-W").map(Number);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() || 7) - 1) + (w - 1) * 7);
  return monday;
}

export function shiftWeek(key: string, n: number): string {
  const d = weekStart(key);
  d.setUTCDate(d.getUTCDate() + 7 * n);
  return weekKey(d);
}

export const isWeekKey = (s: unknown): s is string =>
  typeof s === "string" && /^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$/.test(s);
