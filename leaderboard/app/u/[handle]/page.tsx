import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { currentUser } from "@/lib/auth";
import { publicBase } from "@/lib/board";
import { dashboardFor } from "@/lib/dashboard";
import { compact, hours, money } from "@/lib/format";
import { cardPath, publicProfile } from "@/lib/profile";
import { Dashboard } from "./dashboard";
import { PublicCard } from "./public";

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
  return <PublicCard p={p} handle={handle} isOwner={user?.handle === handle} url={`${publicBase()}/u/${handle}`} />;
}
