import { currentUser } from "@/lib/auth";
import { type Period, loadPlayers, publicBase, rank } from "@/lib/board";
import { fail, ok } from "@/lib/http";

export async function GET(req: Request) {
  if (!(await currentUser())) return fail("not signed in", 401);
  const p = new URL(req.url).searchParams.get("period");
  const period: Period = p === "month" || p === "all" ? p : "week";
  return ok({ period, rows: rank(await loadPlayers(), period), url: `${publicBase()}/?period=${period}` });
}
