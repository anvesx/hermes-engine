import pg from "pg";

// one pool per server instance; reused across hot reloads in dev
const g = globalThis as unknown as { pool?: pg.Pool };
export const pool =
  g.pool ?? (g.pool = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 5 }));

export async function q<T = Record<string, unknown>>(text: string, params: unknown[] = []): Promise<T[]> {
  const r = await pool.query(text, params);
  return r.rows as T[];
}

export async function one<T = Record<string, unknown>>(text: string, params: unknown[] = []): Promise<T | null> {
  return (await q<T>(text, params))[0] ?? null;
}
