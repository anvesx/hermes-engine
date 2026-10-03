import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { glyphRows } from "@/app/term";
import { compact, hours, money } from "@/lib/format";
import { publicProfile } from "@/lib/profile";

export const dynamic = "force-dynamic";

// The link-preview card, drawn as the same terminal window as /u/<handle>. JetBrains Mono (OFL, assets/fonts) is
// bundled because the image renderer only has a sans-serif font built in.
const fonts = Promise.all(["Regular", "Bold"].map((w) => readFile(join(process.cwd(), `assets/fonts/JetBrainsMono-${w}.ttf`))));

const C = { bg: "#0a0a0a", win: "#0c0c0c", bar: "#161616", line: "#2a2a2a", fg: "#e2e2dc", dim: "#8a8a82",
            green: "#5af78e", cyan: "#57c7ff", shadow: "#14532d" };

export async function GET(req: Request, { params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  const p = await publicProfile(handle);
  if (!p) return new Response("not found", { status: 404 });
  const [regular, bold] = await fonts;

  const who = (p.name ?? "anonymous").toLowerCase().replace(/\s+/g, "");
  const big = p.tokens !== null ? { text: compact(p.tokens), cap: "tokens through Claude Code" }
    : p.hours !== null ? { text: `${Math.round(p.hours)}h`, cap: "hours in Claude Code" }
    : p.level ? { text: String(p.level.level), cap: `level ${p.level.level} · ${p.level.title.toLowerCase()}` } : null;
  const rows = big ? glyphRows(big.text) : [];
  const px = rows[0] && rows[0].length > 16 ? 26 : 36;
  const info = [
    p.level && ["level", `${p.level.level} · ${p.level.title}`],
    p.streak && ["streak", `${p.streak.current} weeks`],
    p.tokens !== null && ["tokens", compact(p.tokens)],
    p.hours !== null && ["uptime", hours(p.hours)],
    p.spend !== null && ["spend", money(p.spend)],
    p.badges && ["badges", `${p.badges.length} unlocked`],
  ].filter(Boolean) as [string, string][];
  const badges = (p.badges ?? []).slice(0, 4);

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", padding: 36, background: C.bg, fontFamily: "JetBrains Mono" }}>
        <div style={{ display: "flex", flexDirection: "column", flex: 1, background: C.win, border: `2px solid #2f2f2f`, borderRadius: 18,
                      overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", padding: "14px 22px", background: C.bar, borderBottom: `2px solid ${C.line}`,
                        color: C.dim, fontSize: 20 }}>
            <div style={{ display: "flex", gap: 10 }}>
              {["#ff5f57", "#febc2e", "#28c840"].map((c) => <div key={c} style={{ width: 16, height: 16, borderRadius: 8, background: c }} />)}
            </div>
            <div style={{ display: "flex", flex: 1, justifyContent: "center" }}>{`guest@claude-code: ~/u/${handle}`}</div>
            <div style={{ display: "flex" }}>public</div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", flex: 1, padding: "26px 36px 24px" }}>
            <div style={{ display: "flex", fontSize: 24, color: C.fg }}>
              <span style={{ color: C.green, fontWeight: 700 }}>guest@devxlabs</span>
              <span style={{ color: C.cyan, marginLeft: 12 }}>~</span>
              <span style={{ color: C.green, marginLeft: 12 }}>❯</span>
              <span style={{ marginLeft: 12 }}>{`token-metrics whois ${handle}`}</span>
            </div>

            <div style={{ display: "flex", flex: 1, marginTop: 26, justifyContent: "space-between" }}>
              <div style={{ display: "flex", flexDirection: "column" }}>
                {big ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {rows.map((row, r) => (
                      <div key={r} style={{ display: "flex", gap: 4 }}>
                        {[...row].map((on, c) => (
                          <div key={c} style={{ width: px, height: px, background: on === "1" ? C.green : "transparent",
                                                boxShadow: on === "1" ? `7px 7px 0 ${C.shadow}` : "none" }} />
                        ))}
                      </div>
                    ))}
                  </div>
                ) : <div style={{ display: "flex", fontSize: 30, color: C.dim }}>numbers kept private</div>}
                {big && <div style={{ display: "flex", marginTop: 26, fontSize: 24, color: C.fg }}>
                  {big.cap}<span style={{ color: C.dim, marginLeft: 12 }}>// all time</span></div>}
              </div>

              <div style={{ display: "flex", flexDirection: "column", width: 400, fontSize: 22 }}>
                <div style={{ display: "flex", fontSize: 26, fontWeight: 700, color: C.green }}>
                  {who}<span style={{ color: C.fg, fontWeight: 400 }}>@</span>devxlabs</div>
                <div style={{ display: "flex", height: 2, width: 240, background: C.dim, margin: "10px 0 14px" }} />
                {info.map(([k, v]) => (
                  <div key={k} style={{ display: "flex", marginBottom: 6 }}>
                    <span style={{ width: 120, color: C.cyan, fontWeight: 700 }}>{`${k}:`}</span>
                    <span style={{ color: C.fg }}>{v}</span>
                  </div>
                ))}
                <div style={{ display: "flex", marginTop: 12 }}>
                  {["#282a36", "#ff5c57", "#5af78e", "#f3f99d", "#57c7ff", "#ff6ac1", "#9aedfe", "#f1f1f0"].map((c) => (
                    <div key={c} style={{ width: 34, height: 18, background: c }} />
                  ))}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {badges.map((b) => (
                <div key={b.id} style={{ display: "flex", padding: "6px 14px", border: `2px solid rgba(90,247,142,.5)`, borderRadius: 8,
                                         background: "rgba(90,247,142,.06)", color: C.fg, fontSize: 20 }}>
                  <span style={{ color: C.green, marginRight: 10 }}>[x]</span>{b.name}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    ),
    // a versioned URL (?v= the card's current version) never changes, so it can be cached for good;
    // the bare URL, and any stale version, must be re-rendered almost every time
    { width: 1200, height: 630, fonts: [{ name: "JetBrains Mono", data: regular, weight: 400 }, { name: "JetBrains Mono", data: bold, weight: 700 }],
      headers: { "Cache-Control": new URL(req.url).searchParams.get("v") === p.version
        ? "public, max-age=31536000, immutable" : "public, max-age=0, s-maxage=60, must-revalidate" } },
  );
}
