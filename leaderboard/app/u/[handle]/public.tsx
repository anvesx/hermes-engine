// /u/<handle> for everyone else (and for the owner with ?public=1): the same terminal look as the dashboard, showing
// only the fields the player enabled for their card. Everything here comes from publicProfile(), never from the
// full dashboard data, so hidden fields cannot leak.
import type React from "react";
import Link from "next/link";
import { Figlet, TermWindow } from "@/app/term";
import { compact, hours, money } from "@/lib/format";
import type { publicProfile } from "@/lib/profile";

type Profile = NonNullable<Awaited<ReturnType<typeof publicProfile>>>;

export function PublicCard({ p, handle, isOwner, url }: { p: Profile; handle: string; isOwner: boolean; url: string }) {
  const who = (p.name ?? "anonymous").toLowerCase().replace(/\s+/g, "");
  // the headline number: tokens if shown, else hours, else the level
  const big = p.tokens !== null ? { text: compact(p.tokens), cap: "tokens through Claude Code" }
    : p.hours !== null ? { text: `${Math.round(p.hours)}h`, cap: "hours in Claude Code" }
    : p.level ? { text: String(p.level.level), cap: `level ${p.level.level} · ${p.level.title}` }
    : null;

  const info: [string, React.ReactNode][] = [
    ...(p.name ? [["name", p.name]] as [string, React.ReactNode][] : []),
    ...(p.level ? [["level", `${p.level.level} · ${p.level.title} · ${p.level.points} pts`]] as [string, React.ReactNode][] : []),
    ...(p.streak ? [["streak", `${p.streak.current} weeks (best ${p.streak.best})`]] as [string, React.ReactNode][] : []),
    ...(p.tokens !== null ? [["tokens", compact(p.tokens)]] as [string, React.ReactNode][] : []),
    ...(p.hours !== null ? [["uptime", `${hours(p.hours)} in Claude Code`]] as [string, React.ReactNode][] : []),
    ...(p.spend !== null ? [["spend", `${money(p.spend)} API-equivalent`]] as [string, React.ReactNode][] : []),
    ...(p.badges ? [["badges", `${p.badges.length} unlocked`]] as [string, React.ReactNode][] : []),
  ];
  const stats: [string, string, string][] = [
    ...(p.level ? [["level", String(p.level.level), p.level.title.toLowerCase()]] as [string, string, string][] : []),
    ...(p.streak ? [["streak", `${p.streak.current}w`, `best ${p.streak.best}`]] as [string, string, string][] : []),
    ...(p.hours !== null ? [["active", hours(p.hours), "in Claude Code"]] as [string, string, string][] : []),
    ...(p.spend !== null ? [["spend", money(p.spend), "API-equivalent"]] as [string, string, string][] : []),
  ];

  return (
    <main className="dash public">
      <nav className="dnav">
        <span className="logo"><span className="arrow">❯</span> token-metrics<span className="dim">/u/{handle}</span></span>
        {isOwner ? <Link href={`/u/${handle}`}>cd ~/dashboard</Link> : <Link href="/">cd ../leaderboard</Link>}
      </nav>

      <TermWindow label={`${p.name ?? "A Claude Code user"}'s stats`} title={`guest@claude-code: ~/u/${handle}`} note="public" foot={<>
        <span>measured with <kbd>token-metrics</kbd> for Claude Code</span>
        <span className="ok">● {url}<span className="cursor" /></span>
      </>}>
        <p className="prompt"><span className="ps1">guest@devxlabs</span> <span className="cwd">~</span> <span className="arrow">❯</span> token-metrics whois {handle}</p>
        <div className="term-main">
          <div className="term-left">
            {big ? <><Figlet text={big.text} /><p className="figlet-cap">{big.cap} <span className="dim">// all time</span></p></>
                 : <p className="figlet-cap dim">This player keeps their numbers private.</p>}
            {stats.length > 0 && (
              <div className="term-stats">
                {stats.map(([k, v, e]) => <div key={k}><span>{k}</span><b>{v}</b><em>{e}</em></div>)}
              </div>
            )}
          </div>
          <div className="neofetch">
            <p className="nf-head"><span className="ps1">{who}</span>@<span className="ps1">devxlabs</span></p>
            <p className="nf-rule">{"─".repeat(Math.min(28, who.length + 9))}</p>
            {info.map(([k, v]) => <p key={k}><span className="nf-k">{k}</span><span className="nf-v">{v}</span></p>)}
            <p className="nf-swatch" aria-hidden>{["k", "r", "g", "y", "b", "m", "c", "w"].map((c) => <i key={c} className={`sw-${c}`} />)}</p>
          </div>
        </div>
      </TermWindow>

      {p.badges && p.badges.length > 0 && (
        <>
          <h2>Badges <span className="muted">{p.badges.length} unlocked</span></h2>
          <div className="badges">
            {p.badges.map((b) => (
              <div key={b.id} className="badge on"><b><span className="chk">[✓]</span> {b.name}</b><span>{b.description}</span></div>
            ))}
          </div>
        </>
      )}

    </main>
  );
}
