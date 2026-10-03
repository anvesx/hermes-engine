import Link from "next/link";
import { type Period, publicBase } from "@/lib/board";
import type { Dashboard as Data } from "@/lib/dashboard";
import { compact, hours, money, pct } from "@/lib/format";
import { LEVELS, RULES } from "@/lib/score";
import { PointsBars, ShareBars, SplitBar, WasteLine, WeekBars, dayLabel } from "./charts";

const PERIODS: [Period, string][] = [["week", "This week"], ["month", "Last 4 weeks"], ["all", "All time"]];
const CARD_FIELDS = ["name", "level", "badges", "streak", "tokens", "hours", "spend"];

function ago(d: Date | null) {
  if (!d) return "never";
  const s = (Date.now() - new Date(d).getTime()) / 1000;
  return s < 90 ? "just now" : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago`
    : `${Math.round(s / 86400)} days ago`;
}

function Delta({ now, before, fmt, lowerIsBetter = false }:
  { now: number; before: number | null; fmt: (n: number) => string; lowerIsBetter?: boolean }) {
  if (before === null || before === 0) return null;
  const d = now - before, good = lowerIsBetter ? d < 0 : d > 0;
  if (Math.abs(d) < 1e-9) return <span className="delta">same as last week</span>;
  return <span className={`delta ${lowerIsBetter ? (good ? "good" : "bad") : ""}`}>{d > 0 ? "▲" : "▼"} {fmt(Math.abs(d))} vs last week</span>;
}

export function Dashboard({ data, handle }: { data: Data; handle: string }) {
  const { profile: p, player, totals, trend, ranks, tokens: tk, this_week: tw, last_week: lw } = data;
  const lv = p.level, floor = LEVELS[lv.level - 1][0];
  const toNext = lv.next_at === null ? 1 : (lv.points - floor) / (lv.next_at - floor);
  const weeks = trend.map((t) => t.week);
  const weekPoints = p.weekPoints[trend[trend.length - 1].week] ?? 0;
  const lastPoints = p.weekPoints[trend[trend.length - 2].week] ?? null;
  const card = { ...Object.fromEntries(CARD_FIELDS.map((f) => [f, true])), ...player.user.card_fields };
  const hasData = player.weeks.length > 0;

  return (
    <main className="dash">
      <nav className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <span className="muted">Token Metrics · your dashboard</span>
        <form action="/api/auth/logout" method="post" className="row">
          <Link href="/">Full leaderboard</Link>
          <button className="link">Sign out</button>
        </form>
      </nav>

      <section className="hero">
        <div>
          <div className="eyebrow">Level {lv.level}</div>
          <h1>{player.user.display_name}</h1>
          <div className="hero-title">{lv.title}</div>
          <div className="lvl">
            <div className="lvl-track"><div className="lvl-fill" style={{ width: `${Math.round(toNext * 100)}%` }} /></div>
            <span>{lv.next_at === null ? `${p.points.toLocaleString()} points · top level`
              : `${p.points.toLocaleString()} / ${lv.next_at.toLocaleString()} points to ${LEVELS[lv.level][1]}`}</span>
          </div>
        </div>
        <div className="hero-ranks">
          {([["week", "this week"], ["month", "last 4 weeks"], ["all", "all time"]] as const).map(([k, label]) => (
            <div key={k} className="hero-rank">
              <b>{ranks[k].rank ? `#${ranks[k].rank}` : "–"}</b>
              <span>of {ranks[k].of} {label}</span>
            </div>
          ))}
          <div className="hero-rank"><b>{p.streak_weeks}</b><span>week streak · best {p.best_streak_weeks}</span></div>
        </div>
      </section>
      <p className="muted small">Last synced {ago(player.last_sync_at)}. Run <code>/token-metrics:dashboard</code> in Claude Code to refresh.</p>

      {!hasData && (
        <p className="panel">No stats yet. Run <code>/token-metrics:dashboard</code> in Claude Code to send your first sync.</p>
      )}

      <h2>Token usage</h2>
      <div className="tiles">
        <div className="tile accent"><span>This week</span><b>{compact(tw?.tokens ?? 0)}</b>
          <Delta now={tw?.tokens ?? 0} before={lw?.tokens ?? null} fmt={compact} /></div>
        <div className="tile"><span>Today</span><b>{tk.has_daily ? compact(tk.today) : "–"}</b></div>
        <div className="tile"><span>Last 30 days</span><b>{tk.has_daily ? compact(tk.last30) : "–"}</b></div>
        <div className="tile"><span>Per active day</span><b>{tk.has_daily ? compact(tk.per_active_day) : "–"}</b>
          <span className="delta">last 30 days</span></div>
        <div className="tile"><span>All time</span><b>{compact(totals.tokens)}</b>
          <span className="delta">{totals.sessions.toLocaleString()} sessions</span></div>
        <div className="tile"><span>By subagents</span><b>{tk.has_detail ? pct(tk.agent_share) : "–"}</b>
          <span className="delta">last 4 weeks</span></div>
      </div>
      {tk.has_daily ? (
        <figure className="panel chart" style={{ marginTop: 12 }}>
          <figcaption>Tokens per day <span className="muted">· last {tk.daily.length} days</span></figcaption>
          <WeekBars weeks={tk.daily.map((d) => d.day)} values={tk.daily.map((d) => d.tokens)} fmt={compact}
                    label={dayLabel} every={5} width={1100} height={230} />
        </figure>
      ) : (
        <p className="panel small" style={{ marginTop: 12 }}>Daily tokens and the breakdowns below need plugin 1.5.0 or later.
          Update the plugin, then run <code>/token-metrics:dashboard</code>.</p>
      )}
      {tk.has_detail && (
        <div className="grid2">
          <figure className="panel chart">
            <figcaption>What your tokens are <span className="muted">· last 4 weeks</span></figcaption>
            <SplitBar fmt={compact} parts={[
              { key: "input", label: "Input", value: tk.split.input, note: "new, uncached" },
              { key: "cache_write", label: "Cache write", value: tk.split.cache_write, note: "new context, stored" },
              { key: "cache_read", label: "Cache read", value: tk.split.cache_read, note: "context re-read each call" },
              { key: "output", label: "Output", value: tk.split.output, note: "written by Claude" },
            ]} />
            <p className="muted small">Every call re-reads the whole conversation from cache, so cache reads dominate the count.
              They cost a tenth of input tokens; the leak report shows which ones you could avoid.</p>
          </figure>
          <figure className="panel chart">
            <figcaption>Tokens by model <span className="muted">· last 4 weeks</span></figcaption>
            <ShareBars fmt={compact} rows={tk.models.map(([m, n]) => ({ key: m, label: m[0].toUpperCase() + m.slice(1), value: n }))} />
            {tw && tk.week_split && (
              <p className="muted small">This week: {compact(tw.tokens - tk.week_split.cache_read)} new tokens
                and {compact(tk.week_split.cache_read)} cache reads.</p>
            )}
          </figure>
        </div>
      )}

      <h2>This week</h2>
      <div className="tiles">
        <div className="tile"><span>Points</span><b>{weekPoints}</b><Delta now={weekPoints} before={lastPoints} fmt={String} /></div>
        <div className="tile"><span>Active</span><b>{hours(tw?.active_hours ?? 0)}</b><Delta now={tw?.active_hours ?? 0} before={lw?.active_hours ?? null} fmt={hours} /></div>
        <div className="tile"><span>API-equivalent</span><b>{money(tw?.cost_usd ?? 0)}</b><Delta now={tw?.cost_usd ?? 0} before={lw?.cost_usd ?? null} fmt={money} /></div>
        <div className="tile">
          <span>Waste index</span><b>{tw && tw.active_days ? tw.waste_index.toFixed(2) : "–"}</b>
          {p.baseline !== null && tw && tw.active_days > 0
            ? <span className={`delta ${tw.waste_index <= p.baseline ? "good" : "bad"}`}>
                {tw.waste_index <= p.baseline ? "▼" : "▲"} {pct(Math.abs(tw.waste_index - p.baseline) / p.baseline)} vs baseline</span>
            : <span className="delta">baseline needs 2 weeks with {RULES.minActiveDays}+ active days</span>}
        </div>
      </div>

      <h2>All time</h2>
      <div className="tiles">
        <div className="tile"><span>API-equivalent spend</span><b>{money(totals.cost_usd)}</b></div>
        <div className="tile"><span>Active hours</span><b>{hours(totals.active_hours)}</b></div>
        <div className="tile"><span>Active days</span><b>{totals.active_days}</b>
          {totals.longest_streak_days > 0 && <span className="delta">longest run {totals.longest_streak_days} days</span>}</div>
        <div className="tile"><span>Sessions</span><b>{totals.sessions.toLocaleString()}</b></div>
        <div className="tile"><span>Tasks</span><b>{totals.tasks.toLocaleString()}</b>
          <span className="delta">{totals.tagged_tasks} tagged · {totals.rated_tasks} rated</span></div>
      </div>
      {totals.top_category && <p className="muted small">Most of your tasks are tagged <code>[{totals.top_category}]</code>.</p>}

      <h2>Usage, last {trend.length} weeks</h2>
      <div className="grid3">
        <figure className="panel chart"><figcaption>Tokens per week</figcaption>
          <WeekBars weeks={weeks} values={trend.map((t) => t.tokens)} fmt={compact} width={360} height={170} /></figure>
        <figure className="panel chart"><figcaption>Active hours</figcaption>
          <WeekBars weeks={weeks} values={trend.map((t) => t.active_hours)} fmt={(n) => hours(Math.round(n * 10) / 10)} width={360} height={170} /></figure>
        <figure className="panel chart"><figcaption>API-equivalent spend</figcaption>
          <WeekBars weeks={weeks} values={trend.map((t) => t.cost_usd)} fmt={money} width={360} height={170} /></figure>
      </div>

      <div className="grid2">
        <figure className="panel chart">
          <figcaption>Points by week
            <span className="legend"><i className="key s1" />Participation <i className="key s2" />Improvement</span>
          </figcaption>
          <PointsBars weeks={weeks} a={trend.map((t) => t.participation)} b={trend.map((t) => t.improvement)} />
          <p className="muted small">Participation: {RULES.synced} for syncing, {RULES.hooked} for hooks on {pct(RULES.hookedShare)} of
            sessions, {RULES.perTagged} per tagged task (max {RULES.taggedCap}), {RULES.perRated} per rating (max {RULES.ratedCap}).
            Improvement: 1 point per % below your baseline, up to {RULES.improvementCap}.</p>
        </figure>
        <figure className="panel chart">
          <figcaption>Waste index <span className="muted">· lower is better</span></figcaption>
          <WasteLine weeks={weeks} values={trend.map((t) => t.waste_index)} baseline={p.baseline} />
          <p className="muted small">The share of your spend that went to leaks. Categories overlap, so it can pass 1.0;
            it only ever counts against your own baseline.</p>
        </figure>
      </div>

      <div className="grid2">
        <figure className="panel chart">
          <figcaption>Where your tokens leak <span className="muted">· last 4 weeks</span>
            <span className="legend"><i className="key s1" />You <i className="key tick" />Company</span>
          </figcaption>
          {data.leaks.length
            ? <ShareBars fmt={pct} compareLabel="company"
                rows={data.leaks.map((l) => ({ key: l.id, label: l.name, sub: l.review ? "review" : undefined, value: l.mine, compare: l.company }))} />
            : <p className="muted">No leaks measured in the last 4 weeks.</p>}
          <p className="muted small">Share of your spend per leak category. Run <code>/token-metrics:leak-report</code> for details and fixes.</p>
        </figure>
        <figure className="panel chart">
          <figcaption>Model mix <span className="muted">· by spend</span></figcaption>
          {data.models.length
            ? <ShareBars fmt={money} rows={data.models.map(([m, v]) => ({ key: m, label: m[0].toUpperCase() + m.slice(1), value: v }))} />
            : <p className="muted">No model data yet.</p>}
        </figure>
      </div>

      <h2>Badges <span className="muted">{p.badges.length} earned</span></h2>
      <div className="badges">
        {p.badges.map((b) => (
          <div key={b.id} className="badge on"><b>{b.name}</b><span>{b.description}</span></div>
        ))}
        {p.next_badges.map((b) => (
          <div key={b.id} className="badge">
            <b>{b.name}</b><span>{b.hint}</span>
            <div className="lvl-track small"><div className="lvl-fill" style={{ width: `${Math.round(b.progress * 100)}%` }} /></div>
          </div>
        ))}
      </div>

      <h2 id="leaderboard">Leaderboard</h2>
      <div className="row tabs">
        {PERIODS.map(([k, label]) => (
          <Link key={k} href={`/u/${handle}?period=${k}#leaderboard`} className={k === data.period ? "on" : ""}>{label}</Link>
        ))}
      </div>
      <div className="panel scroll" style={{ marginTop: 12, padding: 8 }}>
        <table>
          <thead>
            <tr><th className="num">#</th><th>Name</th><th>Level</th><th className="num">Points</th><th className="num">Streak</th>
              <th className="num">Badges</th><th className="num">Tokens</th><th className="num">Active</th></tr>
          </thead>
          <tbody>
            {data.board.map((r) => (
              <tr key={r.handle} className={r.handle === handle ? "me" : ""}>
                <td className="num">{r.rank}</td><td>{r.display_name}{r.handle === handle && <span className="muted"> (you)</span>}</td>
                <td>{r.level} · {r.title}</td><td className="num"><b>{r.points.toLocaleString()}</b></td>
                <td className="num">{r.streak_weeks}w</td><td className="num">{r.badges}</td>
                <td className="num muted">{compact(r.tokens)}</td><td className="num muted">{hours(r.active_hours)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Weekly numbers</h2>
      <div className="panel scroll" style={{ padding: 8 }}>
        <table>
          <thead><tr><th>Week</th><th className="num">Tokens</th><th className="num">Spend</th><th className="num">Active</th>
            <th className="num">Days</th><th className="num">Waste</th><th className="num">Points</th></tr></thead>
          <tbody>{[...trend].reverse().filter((t) => t.active_days > 0 || t.participation > 0).map((t) => (
            <tr key={t.week}><td>{t.week}</td><td className="num">{compact(t.tokens)}</td><td className="num">{money(t.cost_usd)}</td>
              <td className="num">{hours(t.active_hours)}</td><td className="num">{t.active_days}</td>
              <td className="num">{t.waste_index === null ? "–" : t.waste_index.toFixed(2)}</td>
              <td className="num">{t.participation + t.improvement}</td></tr>
          ))}</tbody>
        </table>
      </div>

      <h2>Your public card</h2>
      <div className="grid2">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/u/${handle}/card.png`} alt="Your public stats card" className="card-img" />
        <div className="panel">
          <p style={{ marginTop: 0 }}>Anyone with this link sees only the card, not this dashboard:</p>
          <p><a href={`/u/${handle}?public=1`}><code>{`${publicBase()}/u/${handle}`}</code></a></p>
          <p className="muted small">Shows: {CARD_FIELDS.filter((f) => card[f]).join(", ") || "nothing"}.
            Hide fields with <code>/token-metrics:share card --hide spend,name</code>.</p>
        </div>
      </div>
      <p className="muted small" style={{ marginTop: 32 }}>
        Spend is API-equivalent list price, not what the company is billed. Volume is shown but never scored.
      </p>
    </main>
  );
}
