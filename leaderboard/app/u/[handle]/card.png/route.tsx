import { ImageResponse } from "next/og";
import { compact, hours, money } from "@/lib/format";
import { publicProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

export async function GET(_: Request, { params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  const p = await publicProfile(handle);
  if (!p) return new Response("not found", { status: 404 });
  const stats = [
    p.tokens !== null && ["tokens", compact(p.tokens)],
    p.hours !== null && ["active in Claude Code", hours(p.hours)],
    p.spend !== null && ["API-equivalent", money(p.spend)],
    p.streak && ["week streak", String(p.streak.current)],
  ].filter(Boolean) as [string, string][];
  const badges = (p.badges ?? []).slice(0, 6);

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between",
                    padding: 64, background: "linear-gradient(135deg, #1d1d1b 0%, #3a2316 100%)", color: "#f2f1ec", fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 28, color: "#fb923c", letterSpacing: 2 }}>CLAUDE CODE · TOKEN METRICS</div>
          <div style={{ fontSize: 72, fontWeight: 700, marginTop: 12 }}>{p.name ?? "My Claude Code year"}</div>
          {p.level && <div style={{ fontSize: 36, color: "#a3a29b", marginTop: 4 }}>{`Level ${p.level.level} · ${p.level.title}`}</div>}
        </div>
        <div style={{ display: "flex", gap: 48 }}>
          {stats.map(([label, value]) => (
            <div key={label} style={{ display: "flex", flexDirection: "column" }}>
              <div style={{ fontSize: 64, fontWeight: 700 }}>{value}</div>
              <div style={{ fontSize: 24, color: "#a3a29b" }}>{label}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {badges.map((b) => (
            <div key={b.id} style={{ display: "flex", padding: "8px 20px", borderRadius: 999, background: "#fb923c", color: "#1d1d1b", fontSize: 24, fontWeight: 600 }}>
              {b.name}
            </div>
          ))}
        </div>
      </div>
    ),
    { width: 1200, height: 630, headers: { "Cache-Control": "public, max-age=600" } },
  );
}
