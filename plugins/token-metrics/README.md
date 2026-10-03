# token-metrics plugin

Measures every Claude Code task (tokens, cost, latency, frustration, outcome) by category, and ranks
token leaks by estimated cost in 50 categories built from the team's Leak Categories canvas
(see `token-leak-categories.md` at the repo root). Your settings.json hooks are not modified: plugin hooks run
alongside your own. Data stays in `~/.claude/metrics/` unless you join the company leaderboard (below).

## Use

| Type in Claude Code | What happens |
|---|---|
| `[bugfix] the parser drops time zones` | Starts a task in category `bugfix` (the prompt goes to Claude as normal) |
| `rate 3 ok` | Frustration 1-5 and outcome ok / partial / fail for the task just done. Blocked by the hook, so it costs no tokens |
| `/token-metrics:leak-report` | Leak report for the last 30 days (uses a few thousand tokens to display) |
| `/token-metrics:task-report` | Metrics by category |
| `/token-metrics:wrapped` | Your usage in numbers: tokens, API-equivalent spend, active hours, streaks, biggest leaks (local only) |
| `/token-metrics:join you@devxlabs.ai` | Join the company leaderboard: emails you a code, then `/token-metrics:join verify <code> <Your Name>` |
| `/token-metrics:share` | Sync now and show your points, level, rank, badges and public card link |
| `/token-metrics:share preview` | Exactly what syncing sends; sends nothing |
| `/token-metrics:share card --hide spend,name` | Choose what your public card shows (`name, level, badges, streak, tokens, hours, spend`) |
| `/token-metrics:leaderboard [week\|month\|all]` | The company leaderboard |
| `/token-metrics:share leave` | Delete your data on the server and stop syncing |

Free alternative from a terminal:

```bash
python3 ~/.claude/metrics/leak_report.py --days 30 --md leak_report.md
python3 ~/.claude/metrics/analyze.py --csv tasks.csv
```

The scripts are copied to `~/.claude/metrics/` at the start of each session, so this path stays
valid after plugin updates. Add `--all` to the leak report for the full canvas list (core leaks plus all
additional categories), `--all --core` for the core leaks only, and `--ttl 5m` if you use an API key or usage credits.

Newer Claude Code versions record the loaded tool definitions, skill listings and CLAUDE.md files in the
transcript, so the report can show which MCP servers and skills you load but never use. Sessions from older
versions are skipped for those rows.

## Leaderboard

After you join, each session end syncs your stats in the background, at most once an hour. Points come from
participation (an active synced week, hooks on 80%+ of sessions, tagging tasks, rating tasks) and from leaking
less than your own baseline. Tokens, spend and hours are shown and earn badges, but never points. Post your public
card link (`/token-metrics:share` prints it) and the card image previews on LinkedIn and X.

## Privacy

Prompt text is not stored, only length, category and whether it looked like a correction.
Set `CC_METRICS_KEEP_PROMPTS=1` to keep the first 500 characters.

Nothing is sent anywhere until you run `/token-metrics:join`. After that, syncing sends only per-week aggregates:
tokens, API-equivalent spend, active hours and days, session and task counts, tagged and rated task counts, model mix
by spend, and each leak category's share of spend. It never sends prompt text, project names, file paths or session
ids. Your name and stats are visible on the internal leaderboard; your public card shows only the fields you leave on.
`/token-metrics:share leave` deletes everything the server has about you.
