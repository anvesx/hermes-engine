import Link from "next/link";
import { redirect } from "next/navigation";
import { Figlet, SegBar, TermBars, TermWindow } from "@/app/term";
import { ShareBars, WeekBars } from "@/app/u/[handle]/charts";
import { adminUnlocked } from "@/lib/admin";
import { currentUser, isAdmin } from "@/lib/auth";
import { companyStats, loadPlayers, periodWeeks } from "@/lib/board";
import categories from "@/lib/categories.json";
import { compact, hours, money, pct } from "@/lib/format";
import { shiftWeek, weekKey } from "@/lib/weeks";

export const dynamic = "force-dynamic";
const CATS = categories as Record<string, { name: string; group: string; review: boolean }>;
const wk = (k: string) => `w${k.slice(6)}`;
const count = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

// Open to everyone signed in with a work email. Emails and the CSV export are shown only to admins
// (ADMIN_EMAILS) who have also entered the admin password; they reach the password prompt with ?unlock=1.
export default async function Admin({ searchParams }: { searchParams: Promise<{ denied?: string; user?: string; unlock?: string }> }) {
  const user = await currentUser();
  if (!user) redirect("/login");
  const sp = await searchParams;
  const admin = isAdmin(user);
  const full = admin && (await adminUnlocked());
  if (admin && !full && (sp.unlock || sp.denied)) return <Locked denied={!!sp.denied} />;

  const players = await loadPlayers();
  // ?user=<handle> scopes every number, chart and table below to one player
  const sel = players.find((p) => p.user.handle === sp.user) ?? null;
  const scope = sel ? [sel] : players;
  const monthWeeks = periodWeeks("month");
  const month = companyStats(scope, monthWeeks);
  const cur = weekKey(new Date());
  const trend = Array.from({ length: 8 }, (_, i) => shiftWeek(cur, i - 7))
    .map((w) => ({ week: w, ...companyStats(scope, new Set([w])) }));
  const exportUrl = sel ? `/admin/export?user=${encodeURIComponent(sel.user.handle)}` : "/admin/export";
  const roster = players.map((p) => ({ p, s: companyStats([p], monthWeeks) })).sort((a, b) => b.s.tokens - a.s.tokens);
  const weeks = trend.map((t) => t.week);
  // largest first; rows that would print as 0.0% are hidden
  const leaks = Object.entries(month.leak).filter(([, v]) => v >= 0.0005).sort((a, b) => b[1] - a[1]);
  const quiet = scope.filter((p) => !p.last_sync_at || Date.now() - new Date(p.last_sync_at).getTime() > 7 * 86400e3);
  const days = (d: Date | null) => {
    if (!d) return "never";
    const n = Math.floor((Date.now() - new Date(d).getTime()) / 86400e3);
    return n === 0 ? "today" : `${n}d ago`;
  };

  const info: [string, React.ReactNode][] = [
    ...(sel ? [
      ["user", full ? sel.user.email : sel.user.display_name],
      ["level", `${sel.profile.level.level} · ${sel.profile.level.title} · ${sel.profile.points} pts`],
      ["synced", days(sel.last_sync_at)],
    ] as [string, React.ReactNode][] : [
      ["players", <><SegBar f={month.players ? month.active_players / month.players : 0} /> {month.active_players}/{month.players} active</>],
    ] as [string, React.ReactNode][]),
    ["spend", `${money(month.spend)} API-equivalent`],
    ["uptime", `${hours(month.active_hours)} in Claude Code`],
    ["sessions", month.sessions.toLocaleString()],
    ["hooks", <><SegBar f={month.hook_coverage} /> {pct(month.hook_coverage)} of sessions</>],
    ["tasks", `${month.tagged_tasks} tagged · ${month.rated_tasks} rated`],
    ...(leaks[0] ? [["top leak", `${CATS[leaks[0][0]]?.name ?? leaks[0][0]} ${pct(leaks[0][1])}`] as [string, React.ReactNode]] : []),
    ...(sel ? [] : [["quiet", `${quiet.length} not synced in 7d`] as [string, React.ReactNode]]),
  ];

  return (
    <main className="dash">
      <nav className="dnav">
        <span className="logo"><span className="arrow">❯</span> token-metrics<span className="dim">/{full ? "admin" : "team"}</span></span>
        <form action="/api/admin/lock" method="post" className="row">
          <Link href="/">cd ../leaderboard</Link>
          {full && <a href={exportUrl}>wget {sel ? sel.user.handle : "company"}.csv</a>}
          {full && <button className="link">sudo -k</button>}
          {admin && !full && <Link href="/admin?unlock=1">sudo (emails &amp; csv)</Link>}
        </form>
      </nav>

      <form method="get" action="/admin" className="filter">
        <label htmlFor="user"><span className="arrow">$</span> token-metrics company --user</label>
        <select id="user" name="user" defaultValue={sel?.user.handle ?? ""}>
          <option value="">* all players ({players.length})</option>
          {[...players].sort((a, b) => a.user.display_name.localeCompare(b.user.display_name)).map((p) => (
            <option key={p.user.id} value={p.user.handle}>{p.user.display_name}{full ? ` · ${p.user.email}` : ""}</option>
          ))}
        </select>
        <button type="submit">apply ⏎</button>
        {sel && <Link href="/admin">clear ✕</Link>}
      </form>

      <TermWindow label="Company results" title={`root@claude-code: ~/token-metrics/admin${sel ? `/${sel.user.handle}` : ""}`} note={cur} foot={<>
        {full && <span><a href={exportUrl}><kbd>/admin/export</kbd></a> download csv</span>}
        <span className="hide-sm">leak shares are spend-weighted and overlap</span>
        <span className="ok">● {sel ? `${sel.user.display_name} · synced ${days(sel.last_sync_at)}` : `${month.active_players} active · ${month.players} joined`}<span className="cursor" /></span>
      </>}>
        <p className="prompt"><span className="ps1 root">root@devxlabs</span> <span className="cwd">~</span> <span className="arrow root">#</span> token-metrics company --last 4w{sel && ` --user ${sel.user.handle}`}</p>
        <div className="term-main">
          <div className="term-left">
            <Figlet text={compact(month.tokens)} />
            <p className="figlet-cap">{sel ? `tokens by ${sel.user.display_name}` : "tokens across the company"} <span className="dim">// last 4 weeks{sel ? "" : ", all players"}</span></p>
            <div className="term-stats">
              {sel
                ? <div><span>sessions</span><b>{month.sessions.toLocaleString()}</b><em>last 4 weeks</em></div>
                : <div><span>players</span><b>{month.active_players}/{month.players}</b><em>active / joined</em></div>}
              <div><span>spend</span><b>{money(month.spend)}</b><em>API-equivalent</em></div>
              <div><span>active</span><b>{hours(month.active_hours)}</b><em>in Claude Code</em></div>
              <div><span>hooks</span><b>{pct(month.hook_coverage)}</b><em>of sessions</em></div>
            </div>
          </div>
          <div className="neofetch">
            <p className="nf-head"><span className="ps1 root">{sel ? sel.user.display_name.toLowerCase() : "root"}</span>@<span className="ps1">devxlabs</span></p>
            <p className="nf-rule">{"─".repeat(18)}</p>
            {info.map(([k, v]) => <p key={k}><span className="nf-k">{k}</span><span className="nf-v">{v}</span></p>)}
            <p className="nf-swatch" aria-hidden>{["k", "r", "g", "y", "b", "m", "c", "w"].map((c) => <i key={c} className={`sw-${c}`} />)}</p>
          </div>
        </div>
        <TermBars title={`spend/week --last ${weeks.length}w`} labels={weeks} values={trend.map((t) => t.spend)} fmt={money} tick={wk} every={1} />
      </TermWindow>

      <h2>Adoption by week {sel && <span className="muted">{sel.user.display_name}</span>}</h2>
      <div className="grid3">
        {sel
          ? <figure className="panel chart"><figcaption>Tokens</figcaption>
              <WeekBars weeks={weeks} values={trend.map((t) => t.tokens)} fmt={compact} width={360} height={170} every={1} /></figure>
          : <figure className="panel chart"><figcaption>Active players</figcaption>
              <WeekBars weeks={weeks} values={trend.map((t) => t.active_players)} fmt={count} width={360} height={170} every={1} /></figure>}
        <figure className="panel chart"><figcaption>Sessions</figcaption>
          <WeekBars weeks={weeks} values={trend.map((t) => t.sessions)} fmt={count} width={360} height={170} every={1} /></figure>
        <figure className="panel chart"><figcaption>Hook coverage</figcaption>
          <WeekBars weeks={weeks} values={trend.map((t) => t.hook_coverage)} fmt={(n) => `${Math.round(n * 100)}%`} width={360} height={170} every={1} /></figure>
      </div>
      <div className="panel scroll" style={{ marginTop: 18, padding: 8 }}>
        <table>
          <thead><tr><th>Week</th><th className="num">Active players</th><th className="num">Sessions</th><th className="num">Hook coverage</th>
            <th className="num">Tagged</th><th className="num">Rated</th><th className="num">Tokens</th><th className="num">Spend</th></tr></thead>
          <tbody>{[...trend].reverse().map((t) => (
            <tr key={t.week}><td>{t.week}</td><td className="num">{t.active_players}</td><td className="num">{t.sessions}</td>
              <td className="num">{pct(t.hook_coverage)}</td><td className="num">{t.tagged_tasks}</td><td className="num">{t.rated_tasks}</td>
              <td className="num">{compact(t.tokens)}</td><td className="num">{money(t.spend)}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <h2>{sel ? `Biggest leaks for ${sel.user.display_name}` : "Biggest leaks across the company"} <span className="muted">last 4 weeks</span></h2>
      <figure className="panel chart">
        <figcaption>Share of spend per leak category</figcaption>
        {leaks.length
          ? <ShareBars fmt={pct} rows={leaks.map(([k, v]) => ({ key: k, label: `${k.padStart(2, "0")} ${CATS[k]?.name ?? `Category ${k}`}`,
                                                               sub: [CATS[k]?.group, CATS[k]?.review && "review"].filter(Boolean).join(" · ") || undefined, value: v }))} />
          : <p className="muted">No leaks measured in the last 4 weeks.</p>}
        <p className="muted small">Spend-weighted{sel ? "" : " across all players"}. Categories overlap, so the shares don&apos;t add to 100%.</p>
      </figure>

      <h2>Players <span className="muted">{players.length} joined · last 4 weeks · click a name to filter</span></h2>
      <div className="panel scroll" style={{ padding: 8 }}>
        <table>
          <thead><tr><th>Name</th>{full && <th>Email</th>}<th>Level</th><th className="num">Tokens</th><th className="num">Spend</th>
            <th className="num">Active</th><th className="num">Sessions</th><th className="num">Hooks</th><th className="num">Last sync</th></tr></thead>
          <tbody>{roster.map(({ p, s }) => (
            <tr key={p.user.id} className={p === sel ? "me" : ""}>
              <td><Link href={`/admin?user=${encodeURIComponent(p.user.handle)}`}>{p.user.display_name}</Link></td>
              {full && <td className="muted">{p.user.email}</td>}<td>{p.profile.level.level} · {p.profile.level.title}</td>
              <td className="num">{compact(s.tokens)}</td><td className="num">{money(s.spend)}</td><td className="num">{hours(s.active_hours)}</td>
              <td className="num">{s.sessions}</td><td className="num">{pct(s.hook_coverage)}</td><td className="num">{days(p.last_sync_at)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>

      <h2>Not synced in 7 days <span className="muted">{quiet.length}</span></h2>
      {quiet.length
        ? <div className="panel quiet">{quiet.map((p) => (
            <p key={p.user.id}><span className="warn">[!]</span> {p.user.display_name} <span className="dim">· last sync {days(p.last_sync_at)}</span></p>
          ))}</div>
        : <p className="muted">{sel ? `${sel.user.display_name} synced this week.` : "Everyone has synced this week."}</p>}
    </main>
  );
}

/** The password popup: nothing from the admin pages is rendered until the shared password is entered. */
function Locked({ denied }: { denied: boolean }) {
  return (
    <main className="dash lock-screen">
      <div className="lock-backdrop" aria-hidden />
      <div className="lock" role="dialog" aria-modal="true" aria-labelledby="lock-title">
        <TermWindow label="Admin password" title="sudo — token-metrics/admin" note="locked">
          <p className="prompt"><span className="ps1 root">root@devxlabs</span> <span className="cwd">~</span> <span className="arrow root">#</span> sudo token-metrics admin</p>
          <form action="/api/admin/unlock" method="post" className="lock-form">
            <label id="lock-title" htmlFor="pw">[sudo] password for admin:</label>
            <input id="pw" name="password" type="password" autoFocus required autoComplete="current-password" />
            {denied && <p className="lock-err">Sorry, try again.</p>}
            <div className="lock-actions">
              <Link href="/">cancel</Link>
              <button type="submit">unlock ⏎</button>
            </div>
          </form>
        </TermWindow>
      </div>
    </main>
  );
}
