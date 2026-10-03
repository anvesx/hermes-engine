// A second lock on /admin: on top of ADMIN_EMAILS, the admin pages ask for a shared password once per browser.
// The password comes from the ADMIN_PASSWORD environment variable and is never stored in the repo; without it,
// /admin stays locked. The cookie is an HMAC (keyed by the password) over the admin's user id and an expiry, so it
// works for one admin only, expires on its own, and changing the password signs everyone out.
import { createHmac } from "node:crypto";
import { cookies } from "next/headers";
import { currentUser, sameHash, sha256 } from "./auth";

export const ADMIN_COOKIE = "tm_admin";
export const ADMIN_TTL_S = 12 * 3600;

const password = () => process.env.ADMIN_PASSWORD || "";

function sign(userId: string, exp: number) {
  return createHmac("sha256", `tm-admin:${password()}`).update(`${userId}.${exp}`).digest("hex");
}

export const passwordOk = (raw: unknown) =>
  !!password() && typeof raw === "string" && sameHash(sha256(raw), sha256(password()));

export async function adminUnlocked() {
  if (!password()) return false;
  const user = await currentUser();
  const v = (await cookies()).get(ADMIN_COOKIE)?.value;
  if (!user || !v) return false;
  const [id, exp, mac] = v.split(".");
  return id === String(user.id) && Number(exp) > Date.now() / 1000 && !!mac && sameHash(mac, sign(id, Number(exp)));
}

export async function unlockAdmin(userId: string) {
  const exp = Math.floor(Date.now() / 1000) + ADMIN_TTL_S;
  (await cookies()).set(ADMIN_COOKIE, `${userId}.${exp}.${sign(userId, exp)}`, {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: ADMIN_TTL_S,
  });
}

export async function lockAdmin() {
  (await cookies()).delete(ADMIN_COOKIE);
}
