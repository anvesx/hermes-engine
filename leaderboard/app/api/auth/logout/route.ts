import { cookies } from "next/headers";
import { SESSION_COOKIE, sha256 } from "@/lib/auth";
import { q } from "@/lib/db";

export async function POST(req: Request) {
  const jar = await cookies();
  const token = jar.get(SESSION_COOKIE)?.value;
  if (token) await q("DELETE FROM tokens WHERE token_hash = $1", [sha256(token)]);
  jar.delete(SESSION_COOKIE);
  return Response.redirect(new URL("/login", req.url), 303);
}
