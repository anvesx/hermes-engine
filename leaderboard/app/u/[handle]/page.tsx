import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { publicBase } from "@/lib/board";
import { compact, hours, money } from "@/lib/format";
import { publicProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ handle: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle } = await params;
  const p = await publicProfile(handle);
  if (!p) return {};
  const title = `${p.name ?? "A Claude Code user"}${p.level ? ` · Level ${p.level.level} ${p.level.title}` : ""}`;
  const bits = [p.tokens !== null && `${compact(p.tokens)} tokens`, p.hours !== null && `${hours(p.hours)} in Claude Code`,
                p.badges && `${p.badges.length} badges`].filter(Boolean).join(" · ");
  const image = `${publicBase()}/u/${handle}/card.png`;
  return {
    title, description: bits,
    openGraph: { title, description: bits, images: [{ url: image, width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, description: bits, images: [image] },
  };
}

export default async function PublicProfile({ params }: Props) {
  const { handle } = await params;
  const p = await publicProfile(handle);
  if (!p) notFound();
  return (
    <main style={{ maxWidth: 760 }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`/u/${handle}/card.png`} alt="Claude Code stats card" style={{ width: "100%", borderRadius: 12, border: "1px solid var(--line)" }} />
      <div className="panel stats" style={{ marginTop: 16 }}>
        {p.level && <div className="stat"><span className="muted">Level {p.level.level}</span><b>{p.level.title}</b></div>}
        {p.streak && <div className="stat"><span className="muted">Streak</span><b>{p.streak.current} weeks</b></div>}
        {p.tokens !== null && <div className="stat"><span className="muted">Tokens</span><b>{compact(p.tokens)}</b></div>}
        {p.hours !== null && <div className="stat"><span className="muted">Active</span><b>{hours(p.hours)}</b></div>}
        {p.spend !== null && <div className="stat"><span className="muted">API-equivalent</span><b>{money(p.spend)}</b></div>}
      </div>
      {p.badges && p.badges.length > 0 && (
        <>
          <h2>Badges</h2>
          <div className="row">{p.badges.map((b) => <span key={b.id} className="pill" title={b.description}>{b.name}</span>)}</div>
        </>
      )}
      <p className="muted" style={{ marginTop: 32 }}>Measured with the token-metrics plugin for Claude Code.</p>
    </main>
  );
}
