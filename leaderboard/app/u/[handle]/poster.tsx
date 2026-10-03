// The top of the dashboard, built to be screenshotted: one giant number, a level sticker, a rank stamp,
// the last 30 days as a bar strip and a ticker of everything else. Server-rendered, no client JS.
import type { Dashboard as Data } from "@/lib/dashboard";
import { compact, hours, money } from "@/lib/format";
import { LEVELS } from "@/lib/score";
import { dayLabel } from "./charts";

const STAR = "✸";

export function Poster({ data, handle }: { data: Data; handle: string }) {
  const { profile: p, player, totals, ranks, tokens: tk, this_week: tw, last_week: lw, trend } = data;
  const lv = p.level, floor = LEVELS[lv.level - 1][0];
  const toNext = lv.next_at === null ? 1 : (lv.points - floor) / (lv.next_at - floor);
  const week = trend[trend.length - 1].week;
  const name = player.user.display_name;
  const big = compact(totals.tokens);
  const unit = /[a-zA-Z]$/.test(big) ? big.slice(-1) : "";
  const wkTokens = tw?.tokens ?? 0, wkDelta = lw?.tokens ? wkTokens - lw.tokens : null;
  const peak = Math.max(...tk.daily.map((d) => d.tokens), 1);
  const ring = `${lv.title} ${STAR} level ${lv.level} ${STAR} ${lv.points} pts ${STAR} `.toUpperCase().repeat(2);

  const ticker = [
    `${compact(totals.tokens)} tokens`, `${hours(totals.active_hours)} in Claude Code`, `${totals.sessions.toLocaleString()} sessions`,
    `${totals.tasks.toLocaleString()} tasks`, ranks.week.rank && `#${ranks.week.rank} this week`, `${p.badges.length} badges`,
    totals.longest_streak_days > 0 && `longest run ${totals.longest_streak_days} days`,
    totals.top_category && `mostly [${totals.top_category}]`, `${money(totals.cost_usd)} API-equivalent`,
  ].filter(Boolean).map((s) => String(s).toUpperCase());

  return (
    <section className="poster" aria-label="Your Claude Code stats">
      <header className="p-top">
        <span><b>TOKEN/METRICS</b> {STAR} CLAUDE CODE, WRAPPED</span>
        <span>{week.replace("-", " · ")} {STAR} @{handle}</span>
      </header>

      <div className="p-main">
        <div className="p-left">
          <div className="p-name">{name}</div>
          <div className="p-big" aria-label={`${big} tokens`}>
            {unit ? <>{big.slice(0, -1)}<span>{unit}</span></> : big}
          </div>
          <div className="p-cap">tokens pushed through Claude Code
            <span> {STAR} {totals.active_days} days {STAR} {totals.sessions.toLocaleString()} sessions</span></div>
        </div>

        <div className="p-right">
          <div className="p-sticker" title={`Level ${lv.level}: ${lv.title}`}>
            <svg viewBox="0 0 200 200" className="p-ring" aria-hidden>
              <defs><path id="p-ring" d="M100,100 m-80,0 a80,80 0 1,1 160,0 a80,80 0 1,1 -160,0" /></defs>
              <text><textPath href="#p-ring" textLength="502" lengthAdjust="spacing">{ring}</textPath></text>
            </svg>
            <div className="p-lvl"><span>LVL</span><b>{lv.level}</b></div>
          </div>
          <div className="p-stamp">
            <b>{ranks.week.rank ? `#${ranks.week.rank}` : "—"}</b>
            <span>this week<br />of {ranks.week.of}</span>
          </div>
          <div className="p-xp">
            <div className="p-segs">
              {Array.from({ length: 10 }, (_, i) => <i key={i} className={i < Math.round(toNext * 10) ? "on" : ""} />)}
            </div>
            <span>{lv.next_at === null ? "MAX LEVEL" : `${lv.points}/${lv.next_at} → ${LEVELS[lv.level][1].toUpperCase()}`}</span>
          </div>
        </div>
      </div>

      <div className="p-stats">
        <div><span>This week</span><b>{compact(wkTokens)}</b>
          {wkDelta !== null && <em>{wkDelta >= 0 ? "▲" : "▼"} {compact(Math.abs(wkDelta))}</em>}</div>
        <div><span>In the chair</span><b>{hours(totals.active_hours)}</b><em>all time</em></div>
        <div><span>API-equivalent</span><b>{money(totals.cost_usd)}</b><em>list price</em></div>
        <div><span>Streak</span><b>{p.streak_weeks}<small> wk</small></b><em>best {p.best_streak_weeks}</em></div>
      </div>

      {tk.has_daily && (
        <div className="p-bars" aria-label="Tokens per day, last 30 days">
          <div className="p-bars-head"><span>LAST {tk.daily.length} DAYS</span><span>PEAK {compact(peak)} / DAY</span></div>
          <div className="p-bars-row">
            {tk.daily.map((d, i) => (
              <i key={d.day} title={`${dayLabel(d.day)}: ${compact(d.tokens)}`}
                 className={i === tk.daily.length - 1 ? "now" : d.tokens === 0 ? "off" : ""}
                 style={{ height: `${Math.max(4, (d.tokens / peak) * 100)}%` }} />
            ))}
          </div>
        </div>
      )}

      <div className="p-ticker" aria-hidden>
        <div>{[0, 1].map((k) => <span key={k}>{ticker.map((t) => `${t}  ${STAR}  `).join("")}</span>)}</div>
      </div>
    </section>
  );
}
