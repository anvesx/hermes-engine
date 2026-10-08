import Link from "next/link";
import { redirect } from "next/navigation";
import { currentUser } from "@/lib/auth";
import { type Period, loadPlayers, rank } from "@/lib/board";
import { compact, hours, money } from "@/lib/format";

export const dynamic = "force-dynamic";
const PERIODS: [Period, string][] = [["week", "This week"], ["month", "Last 4 weeks"], ["all", "All time"]];

export default async function Leaderboard({ searchParams }: { searchParams: Promise<{ period?: string }> }) {
  const user = await currentUser();
  if (!user) redirect("/login");
  const sp = await searchParams;
  const period: Period = sp.period === "month" || sp.period === "all" ? sp.period : "week";
  const players = await loadPlayers();
  const rows = rank(players, period);
  const me = players.find((p) => p.user.id === user.id);

  return (
    <main>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1>Token Leaderboard</h1>
          <p className="muted" style={{ margin: 0 }}>
            Points come from tagging, rating, keeping hooks on, and leaking less than your own baseline. Volume is shown, never scored.
          </p>
        </div>
        <form action="/api/auth/logout" method="post" className="row">
          <Link href="/admin">Team dashboard</Link>
          <Link href={`/u/${user.handle}`}>My dashboard</Link>
          <button className="link">Sign out</button>
        </form>
      </div>

      {me && (
        <div className="panel stats" style={{ marginTop: 24 }}>
          <div className="stat"><span className="muted">Level {me.profile.level.level}</span><b>{me.profile.level.title}</b></div>
          <div className="stat"><span className="muted">Points</span><b>{me.profile.points.toLocaleString()}</b></div>
          <div className="stat"><span className="muted">Streak</span><b>{me.profile.streak_weeks} wk</b></div>
          <div className="stat"><span className="muted">Badges</span><b>{me.profile.badges.length}</b></div>
          <div className="stat"><span className="muted">Next up</span><b style={{ fontSize: 15 }}>
            {me.profile.next_badges[0] ? `${me.profile.next_badges[0].name}: ${me.profile.next_badges[0].hint}` : "All badges earned"}
          </b></div>
        </div>
      )}
      {!me?.weeks.length && (
        <p className="panel" style={{ marginTop: 16 }}>
          No stats from you yet. In Claude Code run <code>/token-metrics:join {user.email}</code> to start syncing.
        </p>
      )}

      <div className="row tabs" style={{ marginTop: 24 }}>
        {PERIODS.map(([p, label]) => <Link key={p} href={`/?period=${p}`} className={p === period ? "on" : ""}>{label}</Link>)}
      </div>
      <div className="panel scroll" style={{ marginTop: 12, padding: 8 }}>
        <table>
          <thead>
            <tr>
              <th className="num">#</th><th>Name</th><th>Level</th><th className="num">Points</th><th className="num">Streak</th>
              <th className="num">Badges</th><th className="num">Tokens</th><th className="num">Active</th><th className="num">Spend</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.handle} className={r.handle === user.handle ? "me" : ""}>
                <td className="num">{r.rank}</td>
                <td><Link href={`/u/${r.handle}`}>{r.display_name}</Link></td>
                <td>{r.level} · {r.title}</td>
                <td className="num"><b>{r.points.toLocaleString()}</b></td>
                <td className="num">{r.streak_weeks}w</td>
                <td className="num">{r.badges}</td>
                <td className="num muted">{compact(r.tokens)}</td>
                <td className="num muted">{hours(r.active_hours)}</td>
                <td className="num muted">{money(r.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="muted" style={{ padding: 12 }}>Nobody has synced yet.</p>}
      </div>
      <p className="muted">Spend is API-equivalent list price, not what the company is billed.</p>
    </main>
  );
}
