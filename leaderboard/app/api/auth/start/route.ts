import { CODE_TTL_MIN, clientIp, newCode, normaliseEmail, sha256 } from "@/lib/auth";
import { one, q } from "@/lib/db";
import { sendCode } from "@/lib/email";
import { BodyError, fail, ok, readJson } from "@/lib/http";

const PER_EMAIL_HOUR = 5;
const PER_IP_HOUR = 20;

export async function POST(req: Request) {
  let body: { email?: unknown };
  try {
    body = (await readJson(req, 1_000)) as { email?: unknown };
  } catch (e) {
    return e instanceof BodyError ? fail(e.message, e.status) : fail("bad request");
  }
  const email = normaliseEmail(body?.email);
  if (!email) return fail("use your work email", 400);
  const ip = await clientIp();
  const counts = await one<{ by_email: string; by_ip: string }>(
    `SELECT count(*) FILTER (WHERE email = $1) AS by_email, count(*) FILTER (WHERE ip = $2) AS by_ip
       FROM login_codes WHERE created_at > now() - interval '1 hour' AND (email = $1 OR ip = $2)`,
    [email, ip],
  );
  if (Number(counts?.by_email) >= PER_EMAIL_HOUR || Number(counts?.by_ip) >= PER_IP_HOUR)
    return fail("too many codes requested; try again in an hour", 429);
  const code = newCode();
  await q("UPDATE login_codes SET used = true WHERE email = $1 AND NOT used", [email]);
  await q(
    `INSERT INTO login_codes (email, code_hash, ip, expires_at) VALUES ($1, $2, $3, now() + make_interval(mins => $4))`,
    [email, sha256(code), ip, CODE_TTL_MIN],
  );
  try {
    await sendCode(email, code);
  } catch (e) {
    console.error("sendCode failed", e);
    return fail("could not send the email; try again later", 502);
  }
  return ok({ sent: true });
}
