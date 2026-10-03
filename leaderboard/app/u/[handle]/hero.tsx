// The top of the dashboard as a terminal screen, built to be screenshotted: the all-time token count in a block
// font, a neofetch-style info panel, this week's numbers, the last 30 days as a bar chart and a key-hint footer.
// Server-rendered, no client JS.
import type React from "react";
import type { Dashboard as Data } from "@/lib/dashboard";
import { compact, hours, money } from "@/lib/format";
import { LEVELS } from "@/lib/score";
import { dayLabel } from "./charts";

// 3x5 pixel glyphs; each lit pixel is drawn as two full blocks so it comes out roughly square in a mono font
const GLYPHS: Record<string, string[]> = {
  "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "001", "001", "001"],
  "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
  ".": ["0", "0", "0", "0", "1"], k: ["101", "101", "110", "101", "101"],
  B: ["110", "101", "110", "101", "110"], M: ["10001", "11011", "10101", "10001", "10001"],
};

/** Big text as a 5-row pixel grid. Drawn with cells, not block characters, which most web font subsets lack. */
function Figlet({ text }: { text: string }) {
  const chars = [...text].filter((c) => GLYPHS[c]);
  const rows = [0, 1, 2, 3, 4].map((r) => chars.map((c) => GLYPHS[c][r]).join("0"));
  return (
    <div className="figlet" role="img" aria-label={text} style={{ gridTemplateColumns: `repeat(${rows[0].length}, var(--px))` }}>
      {rows.flatMap((row, r) => [...row].map((on, c) => <i key={`${r}-${c}`} className={on === "1" ? "on" : ""} />))}
    </div>
  );
}

/** A segmented progress bar, the web version of ██████░░░░. */
export function SegBar({ f, n = 10 }: { f: number; n?: number }) {
  const on = Math.max(0, Math.min(n, Math.round(f * n)));
  return <span className="segbar" aria-hidden>{Array.from({ length: n }, (_, i) => <i key={i} className={i < on ? "on" : ""} />)}</span>;
}

export function Hero({ data, handle, synced }: { data: Data; handle: string; synced: string }) {
  const { profile: p, player, totals, ranks, tokens: tk, this_week: tw, last_week: lw, trend } = data;
  const lv = p.level, floor = LEVELS[lv.level - 1][0];
  const toNext = lv.next_at === null ? 1 : (lv.points - floor) / (lv.next_at - floor);
  const week = trend[trend.length - 1].week;
  const user = player.user.display_name.toLowerCase().replace(/\s+/g, "");
  const big = compact(totals.tokens);
  const wk = tw?.tokens ?? 0, wkDelta = lw?.tokens ? wk - lw.tokens : null;
  const peak = Math.max(...tk.daily.map((d) => d.tokens), 1);
  const rank = (r: { rank: number | null; of: number }) => (r.rank ? `#${r.rank}/${r.of}` : "–");

  const info: [string, React.ReactNode][] = [
    ["level", `${lv.level} · ${lv.title}`],
    ["xp", <><SegBar f={toNext} /> {lv.next_at === null ? "max" : `${lv.points}/${lv.next_at} → ${LEVELS[lv.level][1].toLowerCase()}`}</>],
    ["rank", `${rank(ranks.week)} wk · ${rank(ranks.month)} 4wk · ${rank(ranks.all)} all`],
    ["streak", `${p.streak_weeks} weeks (best ${p.best_streak_weeks})`],
    ["uptime", `${hours(totals.active_hours)} over ${totals.active_days} days`],
    ["sessions", `${totals.sessions.toLocaleString()} · ${totals.tasks.toLocaleString()} tasks`],
    ["spend", `${money(totals.cost_usd)} API-equivalent`],
    ["badges", `${p.badges.length} unlocked`],
    ...(totals.top_category ? [["top tag", `[${totals.top_category}]`] as [string, React.ReactNode]] : []),
  ];

  return (
    <section className="term" aria-label="Your Claude Code stats">
      <div className="term-bar">
        <span className="dots"><i /><i /><i /></span>
        <span>{user}@claude-code: ~/token-metrics</span>
        <span>{week}</span>
      </div>

      <div className="term-body">
        <p className="prompt"><span className="ps1">{user}@claude-code</span> <span className="cwd">~</span> <span className="arrow">❯</span> token-metrics wrapped --all-time</p>

        <div className="term-main">
          <div className="term-left">
            <Figlet text={big} />
            <p className="figlet-cap">tokens through Claude Code <span className="dim">// since you started</span></p>

            <div className="term-stats">
              <div><span>this_week</span><b>{compact(wk)}</b>
                {wkDelta !== null && <em className={wkDelta >= 0 ? "up" : "down"}>{wkDelta >= 0 ? "+" : "-"}{compact(Math.abs(wkDelta))} vs last</em>}</div>
              <div><span>today</span><b>{tk.has_daily ? compact(tk.today) : "–"}</b><em>tokens</em></div>
              <div><span>per_day</span><b>{tk.has_daily ? compact(tk.per_active_day) : "–"}</b><em>active-day avg</em></div>
              <div><span>subagents</span><b>{tk.has_detail ? `${Math.round(tk.agent_share * 100)}%` : "–"}</b><em>last 4 weeks</em></div>
            </div>
          </div>

          <div className="neofetch">
            <p className="nf-head"><span className="ps1">{user}</span>@<span className="ps1">devxlabs</span></p>
            <p className="nf-rule">{"─".repeat(Math.min(28, user.length + 9))}</p>
            {info.map(([k, v]) => (
              <p key={k}><span className="nf-k">{k}</span><span className="nf-v">{v}</span></p>
            ))}
            <p className="nf-swatch" aria-hidden>{["k", "r", "g", "y", "b", "m", "c", "w"].map((c) => <i key={c} className={`sw-${c}`} />)}</p>
          </div>
        </div>

        {tk.has_daily && (
          <div className="term-chart">
            <div className="tc-head"><span>tokens/day --last {tk.daily.length}d</span><span className="dim">peak {compact(peak)}</span></div>
            <div className="tc-plot">
              <div className="tc-axis"><span>{compact(peak)}</span><span>{compact(peak / 2)}</span><span>0</span></div>
              <div className="tc-bars">
                {tk.daily.map((d, i) => (
                  <i key={d.day} title={`${dayLabel(d.day)}: ${compact(d.tokens)}`}
                     className={i === tk.daily.length - 1 ? "now" : d.tokens === 0 ? "off" : ""}
                     style={{ height: `${Math.max(2, (d.tokens / peak) * 100)}%` }} />
                ))}
              </div>
            </div>
            <div className="tc-x">
              {tk.daily.map((d, i) => <span key={d.day}>{(tk.daily.length - 1 - i) % 7 === 0 ? dayLabel(d.day).toLowerCase() : ""}</span>)}
            </div>
          </div>
        )}
      </div>

      <div className="term-foot">
        <span><kbd>/token-metrics:dashboard</kbd> refresh</span>
        <span><kbd>/token-metrics:leak-report</kbd> leaks</span>
        <span className="hide-sm"><kbd>?public=1</kbd> share card</span>
        <span className="ok">● synced {synced} · @{handle}<span className="cursor" /></span>
      </div>
    </section>
  );
}
