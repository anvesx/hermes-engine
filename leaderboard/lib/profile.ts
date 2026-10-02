import { loadPlayers } from "./board";

/** A player's public view: only the fields they enabled for their card. */
export async function publicProfile(handle: string) {
  const players = await loadPlayers();
  const pl = players.find((p) => p.user.handle === handle);
  if (!pl) return null;
  const f = { name: true, level: true, badges: true, streak: true, tokens: true, hours: true, spend: true, ...pl.user.card_fields };
  const p = pl.profile;
  return {
    name: f.name ? pl.user.display_name : null,
    level: f.level ? p.level : null,
    badges: f.badges ? p.badges : null,
    streak: f.streak ? { current: p.streak_weeks, best: p.best_streak_weeks } : null,
    tokens: f.tokens ? p.volume.tokens : null,
    hours: f.hours ? p.volume.active_hours : null,
    spend: f.spend ? p.volume.cost_usd : null,
  };
}
