import { adminUnlocked } from "@/lib/admin";
import { currentUser, isAdmin } from "@/lib/auth";
import { q } from "@/lib/db";
import type { Week } from "@/lib/validate";

const COLS = ["tokens", "cost_usd", "active_hours", "active_days", "sessions", "hook_sessions", "tasks",
              "tagged_tasks", "rated_tasks", "top_category", "waste_index"] as const;

const cell = (v: unknown) => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

export async function GET(req: Request) {
  const user = await currentUser();
  if (!isAdmin(user)) return new Response("not found", { status: 404 });
  if (!(await adminUnlocked())) return Response.redirect(new URL("/admin", req.url), 303);
  // ?user=<handle> limits the export to one player, matching the filter on /admin
  const handle = new URL(req.url).searchParams.get("user");
  const rows = await q<{ email: string; display_name: string; week: string; payload: Week }>(
    `SELECT u.email, u.display_name, s.week, s.payload FROM weekly_stats s JOIN users u ON u.id = s.user_id
     ${handle ? "WHERE u.handle = $1" : ""} ORDER BY s.week, u.email`,
    handle ? [handle] : [],
  );
  const cats = Array.from({ length: 50 }, (_, i) => String(i + 1));
  const lines = [["email", "name", "week", ...COLS, ...cats.map((c) => `leak_${c}`)].join(",")];
  for (const r of rows)
    lines.push([r.email, r.display_name, r.week, ...COLS.map((c) => r.payload[c]), ...cats.map((c) => r.payload.leak_share[c])]
      .map(cell).join(","));
  return new Response(lines.join("\n") + "\n", {
    headers: { "Content-Type": "text/csv", "Content-Disposition": `attachment; filename="token-metrics${handle ? `-${handle.replace(/[^a-z0-9-]/gi, "")}` : ""}.csv"` },
  });
}
