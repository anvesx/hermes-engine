// A second lock on /admin: on top of ADMIN_EMAILS, the admin pages ask for a shared password once per browser.
// The cookie holds a hash of the password, never the password, so changing the password signs everyone out.
import { cookies } from "next/headers";
import { sameHash, sha256 } from "./auth";

export const ADMIN_PASSWORD = "Admin12@#";
export const ADMIN_COOKIE = "tm_admin";
export const ADMIN_TTL_S = 12 * 3600;

const unlockValue = () => sha256(`tm-admin:${ADMIN_PASSWORD}`);

export const passwordOk = (raw: unknown) => typeof raw === "string" && sameHash(sha256(raw), sha256(ADMIN_PASSWORD));

export async function adminUnlocked() {
  const v = (await cookies()).get(ADMIN_COOKIE)?.value;
  return !!v && sameHash(v, unlockValue());
}

export async function unlockAdmin() {
  (await cookies()).set(ADMIN_COOKIE, unlockValue(), {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/", maxAge: ADMIN_TTL_S,
  });
}

export async function lockAdmin() {
  (await cookies()).delete(ADMIN_COOKIE);
}
