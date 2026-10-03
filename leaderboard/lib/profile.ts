import { createHash } from "node:crypto";
import { type Player, loadPlayers } from "./board";

/** A player's public view: only the fields they enabled for their card. */
export async function publicProfile(handle: string) {
  const players = await loadPlayers();
  const pl = players.find((p) => p.user.handle === handle);
  if (!pl) return null;
  const f = { name: true, level: true, badges: true, streak: true, tokens: true, hours: true, spend: true, ...pl.user.card_fields };
  const p = pl.profile;
  return {
    version: cardVersion(pl),
    name: f.name ? pl.user.display_name : null,
    level: f.level ? p.level : null,
    badges: f.badges ? p.badges : null,
    streak: f.streak ? { current: p.streak_weeks, best: p.best_streak_weeks } : null,
    tokens: f.tokens ? p.volume.tokens : null,
    hours: f.hours ? p.volume.active_hours : null,
    spend: f.spend ? p.volume.cost_usd : null,
  };
}

/** The card image's design generation; bump it whenever card.png changes. */
export const CARD_DESIGN = "term-1";

/**
 * Changes whenever anything on the card can change (a sync, a rename, hidden fields), so the card URL can carry it:
 * a new image is a new URL, and CDNs and link previews can cache each one for as long as they like.
 * CARD_DESIGN is part of the key, so a redesign gets new URLs too.
 */
export function cardVersion(pl: Player) {
  const key = JSON.stringify([CARD_DESIGN, pl.last_sync_at, pl.user.display_name, pl.user.card_fields]);
  return createHash("sha256").update(key).digest("hex").slice(0, 10);
}

export const cardPath = (handle: string, version: string) => `/u/${handle}/card.png?v=${version}`;
