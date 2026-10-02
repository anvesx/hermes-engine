import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { currentUser, isAdmin } from "@/lib/auth";
import { companyStats, loadPlayers, periodWeeks } from "@/lib/board";
import categories from "@/lib/categories.json";
import { compact, hours, money, pct } from "@/lib/format";
import { shiftWeek, weekKey } from "@/lib/weeks";

export const dynamic = "force-dynamic";
const CATS = categories as Record<string, { name: string; group: string; review: boolean }>;

export default async function Admin() {
  const user = await currentUser();
  if (!user) redirect("/login");
  if (!isAdmin(user)) notFound();
  const players = await loadPlayers();
  const month = companyStats(players, periodWeeks("month"));
  const cur = weekKey(new Date());
  const trend = Array.from({ length: 8 }, (_, i) => shiftWeek(cur, i - 7))
    .map((w) => ({ week: w, ...companyStats(players, new Set([w])) }));
  const leaks = Object.entries(month.leak).sort((a, b) => b[1] - a[1]);
  const top = leaks[0]?.[1] || 1;
  const quiet = players.filter((p) => !p.last_sync_at || Date.now() - new Date(p.last_sync_at).getTime() > 7 * 86400e3);

  return (
    <main>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Company results</h1>
        <div className="row"><Link href="/">Leaderboard</Link><a href="/admin/export">Download CSV</a></div>
      </div>
      <p className="muted">Last 4 weeks, all players. Leak shares are spend-weighted; categories overlap, so they don't add to 100%.</p>

      <div className="panel stats">
        <div className="stat"><span className="muted">Players</span><b>{month.active_players} / {month.players}</b></div>
        <div className="stat"><span className="muted">Spend</span><b>{money(month.spend)}</b></div>
        <div className="stat"><span className="muted">Tokens</span><b>{compact(month.tokens)}</b></div>
        <div className="stat"><span className="muted">Active</span><b>{hours(month.active_hours)}</b></div>
        <div className="stat"><span className="muted">Hook coverage</span><b>{pct(month.hook_coverage)}</b></div>
        <div className="stat"><span className="muted">Tagged / rated</span><b>{month.tagged_tasks} / {month.rated_tasks}</b></div>
      </div>

      <h2>Adoption by week</h2>
      <div className="panel scroll" style={{ padding: 8 }}>
        <table>
          <thead><tr><th>Week</th><th className="num">Active players</th><th className="num">Sessions</th><th className="num">Hook coverage</th>
            <th className="num">Tagged</th><th className="num">Rated</th><th className="num">Spend</th></tr></thead>
          <tbody>{trend.map((t) => (
            <tr key={t.week}><td>{t.week}</td><td className="num">{t.active_players}</td><td className="num">{t.sessions}</td>
              <td className="num">{pct(t.hook_coverage)}</td><td className="num">{t.tagged_tasks}</td><td className="num">{t.rated_tasks}</td>
              <td className="num">{money(t.spend)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <h2>Biggest leaks across the company</h2>
      <div className="panel scroll" style={{ padding: 8 }}>
        <table>
          <thead><tr><th className="num">#</th><th>Leak</th><th>Group</th><th className="num">Share</th><th style={{ width: "30%" }}></th></tr></thead>
          <tbody>{leaks.map(([k, v]) => (
            <tr key={k}><td className="num">{k}</td>
              <td>{CATS[k]?.name}{CATS[k]?.review && <span className="muted"> (review)</span>}</td>
              <td className="muted">{CATS[k]?.group}</td><td className="num">{pct(v)}</td>
              <td><div className="bar" style={{ width: `${(v / top) * 100}%` }} /></td></tr>
          ))}</tbody>
        </table>
      </div>

      {quiet.length > 0 && (
        <>
          <h2>Not synced in 7 days</h2>
          <p>{quiet.map((p) => p.user.display_name).join(", ")}</p>
        </>
      )}
    </main>
  );
}
