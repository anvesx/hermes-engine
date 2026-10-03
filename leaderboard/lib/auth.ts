import { createHash, randomBytes, randomInt, timingSafeEqual } from "node:crypto";
import { cookies, headers } from "next/headers";
import { one, q } from "./db";

export const SESSION_COOKIE = "tm_session";
export const CODE_TTL_MIN = 10;
export const MAX_CODE_ATTEMPTS = 5;

export type User = {
  id: string;
  email: string;
  display_name: string;
  handle: string;
  card_fields: Record<string, boolean>;
  lifetime: Record<string, unknown> | null;
  days: { day: string; tokens: number; cost_usd: number; active_hours: number }[] | null;
  created_at: Date;
};

export const sha256 = (s: string) => createHash("sha256").update(s).digest("hex");
export const newToken = () => randomBytes(32).toString("base64url");
export const newCode = () => String(randomInt(0, 1_000_000)).padStart(6, "0");

export function sameHash(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export function normaliseEmail(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const email = raw.trim().toLowerCase();
  if (email.length > 200 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  const domains = (process.env.ALLOWED_DOMAINS || "devxlabs.ai").split(",").map((d) => d.trim().toLowerCase());
  return domains.includes(email.split("@")[1]) ? email : null;
}

export function isAdmin(user: User | null) {
  const admins = (process.env.ADMIN_EMAILS || "").split(",").map((e) => e.trim().toLowerCase());
  return !!user && admins.includes(user.email);
}

async function userForToken(token: string | undefined): Promise<User | null> {
  if (!token) return null;
  return one<User>(
    "SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = $1",
    [sha256(token)],
  );
}

/** The signed-in user: a Bearer token (CLI) or the session cookie (website). */
export async function currentUser(): Promise<User | null> {
  const h = (await headers()).get("authorization");
  if (h?.startsWith("Bearer ")) return userForToken(h.slice(7).trim());
  return userForToken((await cookies()).get(SESSION_COOKIE)?.value);
}

export async function clientIp() {
  const h = await headers();
  return (h.get("x-forwarded-for") || "").split(",")[0].trim() || h.get("x-real-ip") || "unknown";
}

export function slug(name: string) {
  const base = name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 24);
  return `${base || "player"}-${randomBytes(3).toString("hex")}`;
}

type UserRow = { id: string; handle: string; display_name: string };

/** Finds the user by email or creates them. `rename` updates an existing user's name to `rawName`. */
export async function findOrCreateUser(email: string, rawName: unknown, rename: boolean): Promise<UserRow> {
  let name = typeof rawName === "string" ? rawName.trim().replace(/\s+/g, " ").slice(0, 40) : "";
  if (/^[\d\s]+$/.test(name)) name = "";   // a pasted sign-in code, not a name
  const user = await one<UserRow>("SELECT id, handle, display_name FROM users WHERE email = $1", [email]);
  if (!user) {
    const shown = name || email.split("@")[0];
    return (await one<UserRow>("INSERT INTO users (email, display_name, handle) VALUES ($1, $2, $3) RETURNING id, handle, display_name",
                               [email, shown, slug(shown)]))!;
  }
  if (rename && name && name !== user.display_name) {
    await q("UPDATE users SET display_name = $1 WHERE id = $2", [name, user.id]);
    user.display_name = name;
  }
  return user;
}
