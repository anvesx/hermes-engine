import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { currentUser } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { dashboardFor } from "@/lib/dashboard";
import { compact, hours, money } from "@/lib/format";
import { cardPath, publicProfile } from "@/lib/profile";
import { Dashboard } from "./dashboard";

export const dynamic = "force-dynamic";
type Props = { params: Promise<{ handle: string }>; searchParams: Promise<{ period?: string; public?: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle } = await params;
  const p = await publicProfile(handle);
  if (!p) return {};
  const title = `${p.name ?? "A Claude Code user"}${p.level ? ` · Level ${p.level.level} ${p.level.title}` : ""}`;
  const bits = [p.tokens !== null && `${compact(p.tokens)} tokens`, p.hours !== null && `${hours(p.hours)} in Claude Code`,
                p.badges && `${p.badges.length} badges`].filter(Boolean).join(" · ");
  const image = `${publicBase()}${cardPath(handle, p.version)}`;
  return {
    title, description: bits,
    openGraph: { title, description: bits, images: [{ url: image, width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, description: bits, images: [image] },
  };
}

export default async function Profile({ params, searchParams }: Props) {
  const { handle } = await params;
  const sp = await searchParams;
  // the owner, signed in, gets the full dashboard; everyone else (and ?public=1) sees only the public card
  const user = await currentUser();
  if (user?.handle === handle && !sp.public) {
    const period = sp.period === "month" || sp.period === "all" ? sp.period : "week";
    const data = await dashboardFor(user.id, period);
    if (data) return <Dashboard data={data} handle={handle} />;
  }
  const p = await publicProfile(handle);
  if (!p) notFound();
  return (
    <main style={{ maxWidth: 760 }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={cardPath(handle, p.version)} alt="Claude Code stats card" style={{ width: "100%", borderRadius: 12, border: "1px solid var(--line)" }} />
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
      <p className="muted" style={{ marginTop: 32 }}>
        Measured with the token-metrics plugin for Claude Code.
        {user?.handle === handle && <> This is what others see. <a href={`/u/${handle}`}>Back to your dashboard</a></>}
      </p>
    </main>
  );
}
