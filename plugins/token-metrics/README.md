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
| `/token-metrics:research-export` | Writes an anonymous aggregate file for the team's token-leak study (totals, shares and session sizes; no prompts, code, paths, project names or ids). `preview` prints it instead. Nothing is sent: you send the file yourself |
| `/token-metrics:dashboard` | The company leaderboard, in one command: joins you if needed, syncs, and opens your personal dashboard in the browser (see below) |

Free alternative from a terminal:

```bash
python3 ~/.claude/metrics/leak_report.py --days 30 --md leak_report.md
python3 ~/.claude/metrics/analyze.py --csv tasks.csv
```

The scripts are copied to `~/.claude/metrics/` at the start of each session, so this path stays
valid after plugin updates. Add `--all` to the leak report for the full canvas list (core leaks plus all
additional categories), `--all --core` for the core leaks only, and `--ttl 5m` if you use an API key or usage credits.
Costs use API list prices for each model version, and cache writes are priced by the lifetime the transcript records.
Item sizes are estimated with a characters-per-token ratio each session measures from its own tool results
(or a per-tokenizer default); the report states the ratio it used.

Newer Claude Code versions record the loaded tool definitions, skill listings and CLAUDE.md files in the
transcript, so the report can show which MCP servers and skills you load but never use. Sessions from older
versions are skipped for those rows.

## Dashboard: `/token-metrics:dashboard`

One command joins, syncs and shows your results:

```
/token-metrics:dashboard you@devxlabs.ai             # first time: emails you a 6-digit code
/token-metrics:dashboard verify <code> <Your Name>   # joins, syncs your history, opens the dashboard
/token-metrics:dashboard                             # every time after that: sync now and open the dashboard
```

From a terminal it needs no Claude Code session and uses no tokens. The first time, it asks for your email, the emailed
code and your name, so one run does everything:

```bash
python3 ~/.claude/metrics/share.py dashboard
alias tm-dashboard='python3 ~/.claude/metrics/share.py dashboard'   # optional, for your shell profile
```

The browser opens `/u/<your-handle>` through a sign-in link that works once, for 5 minutes. Signed in as yourself,
that page is your dashboard: token usage (this week, today, last 30 days, tokens per day, split by type and model,
subagent share), level progress, your rank this week, last 4 weeks and all time, this week against last week,
all-time usage, 12-week charts of tokens, hours, spend, points and waste index against your baseline, your biggest
leaks next to the company's, model mix, badges with progress, and the leaderboard. Anyone else who opens the same
link sees only your public card. Set `CC_METRICS_NO_BROWSER=1` to print the link instead of opening it.

After you join, each session end also syncs your stats in the background, at most once an hour. Points come from
participation (an active synced week, hooks on 80%+ of sessions, tagging tasks, rating tasks) and from leaking
less than your own baseline. Tokens, spend and hours are shown and earn badges, but never points. Post your public
card link and the card image previews on LinkedIn and X.

Other commands, not needed for normal use:

| Command | What it does |
|---|---|
| `/token-metrics:share` | Sync now and print your points, rank, badges and card link, without opening the browser |
| `/token-metrics:share preview` | Exactly what syncing sends; sends nothing |
| `/token-metrics:share card --hide spend,name` | Choose what your public card shows (`name, level, badges, streak, tokens, hours, spend`) |
| `/token-metrics:leaderboard [week\|month\|all]` | The leaderboard as a table in the terminal |
| `/token-metrics:join you@devxlabs.ai` | Join without opening the dashboard (then `/token-metrics:join verify <code> <Your Name>`) |
| `/token-metrics:share leave` | Delete your data on the server and stop syncing |

## Privacy

Prompt text is not stored, only length, category and whether it looked like a correction.
Set `CC_METRICS_KEEP_PROMPTS=1` to keep the first 500 characters.

Nothing is sent anywhere until you join (`/token-metrics:dashboard` or `/token-metrics:join`). After that, syncing sends only per-week aggregates:
tokens (split into input, cache write, cache read and output, by model family and main session vs subagents), daily
token totals for the last 8 weeks, API-equivalent spend, active hours and days, session and task counts, tagged and rated
task counts, model mix by spend, and each leak category's share of spend. It never sends prompt text, project names, file paths or session
ids. Your name and stats are visible on the internal leaderboard; your public card shows only the fields you leave on.
`/token-metrics:share leave` deletes everything the server has about you.
