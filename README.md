# hermes-engine

Measures Claude Code token use and ranks "token leaks" by estimated cost. The repo has two parts:

- `plugins/token-metrics/`: the Claude Code plugin and the report scripts (plain Python 3, no dependencies).
- `leaderboard/`: the opt-in company leaderboard (Next.js on Vercel).

This file covers how to get reports and how to play the leaderboard game. For what each leak category means, see
[`token-leak-categories.md`](token-leak-categories.md). For plugin usage and privacy details, see
[`plugins/token-metrics/README.md`](plugins/token-metrics/README.md).

## Requirements

- Python 3 (standard library only, nothing to install)
- Claude Code, with some history in `~/.claude/projects/`

## Option A: reports straight from the repo (no setup)

Most leaks are detected from the transcripts Claude Code already writes, so you can get a leak report right away.

1. Clone the repo and open it:

   ```bash
   git clone https://github.com/devx-commerce/hermes-engine
   cd hermes-engine
   ```

2. Run the leak report:

   ```bash
   python3 plugins/token-metrics/scripts/leak_report.py --days 30
   ```

3. Optionally save it as Markdown:

   ```bash
   python3 plugins/token-metrics/scripts/leak_report.py --days 30 --md leak_report.md
   ```

Task categories, ratings and idle detection need hook data, so those parts stay empty until you install the plugin (Option B).

## Option B: install the plugin (full reports)

1. Start Claude Code with the plugin loaded:

   ```bash
   claude --plugin-dir /path/to/hermes-engine/plugins/token-metrics
   ```

   The plugin's hooks run alongside your own and do not change your `settings.json`.

2. Start a new session. On SessionStart the hook copies the report scripts to `~/.claude/metrics/` and starts
   writing events to `~/.claude/metrics/events.jsonl`.

3. Work as usual. To get per-task data:
   - Start a task with a category tag: `[bugfix] the parser drops time zones`
   - When it is done, rate it: `rate 3 ok` (frustration 1-5, outcome `ok` / `partial` / `fail`). The hook
     intercepts this, so it costs no tokens.

4. Get the reports from inside Claude Code:

   | Command | Report |
   |---|---|
   | `/token-metrics:leak-report` | Token leaks for the last 30 days, ranked by cost |
   | `/token-metrics:task-report` | Tokens, latency, frustration and success by task category |
   | `/token-metrics:wrapped` | Your usage in numbers: tokens, spend, active hours, streaks, biggest leaks |

   Or from a terminal, which uses no Claude tokens:

   ```bash
   python3 ~/.claude/metrics/leak_report.py --days 30 --md leak_report.md
   python3 ~/.claude/metrics/analyze.py --csv tasks.csv
   python3 ~/.claude/metrics/stats.py
   ```

## Report options

`leak_report.py`:

| Flag | Effect |
|---|---|
| `--days N` | Only the last N days |
| `--since YYYY-MM-DD` | Only from this date (instead of `--days`) |
| `--ttl 5m` | Use if you are on an API key or usage credits (5-minute cache). The default `1h` is for subscriptions |
| `--all` | Full canvas list (core leaks and all additional categories) instead of the 50 curated categories |
| `--all --core` | Core leaks only |
| `--top N` | Examples shown per leak |
| `--md FILE` | Also write the report as Markdown |
| `--root DIR` / `--events FILE` | Read transcripts / hook events from another location |

`analyze.py`:

| Flag | Effect |
|---|---|
| `--since YYYY-MM-DD` | Only tasks from this date |
| `--csv FILE` | Write one row per task to a CSV |
| `--events FILE` | Read hook events from another file |

`stats.py`:

| Flag | Effect |
|---|---|
| `--json` | Print the exact payload a leaderboard sync would send |

Examples:

```bash
python3 ~/.claude/metrics/leak_report.py --since 2026-09-01 --ttl 5m --md out.md
python3 ~/.claude/metrics/leak_report.py --days 30 --all
python3 ~/.claude/metrics/analyze.py --since 2026-10-01 --csv tasks.csv
```

## Gamification: the company leaderboard

Optional and opt-in: nothing leaves your machine until you join. The game rewards using the plugin well and
leaking fewer tokens than your own baseline. Using Claude Code *more* never earns points. Full rules are in
[`gamify.md`](gamify.md); they live in `leaderboard/lib/score.ts`.

You need the plugin installed (Option B above) so the hooks record your sessions.

### Step 1: join

1. Request a sign-in code. The leaderboard URL isn't built into the plugin yet, so pass it once; it is saved for later syncs:

   ```
   /token-metrics:join you@devxlabs.ai --url https://<leaderboard-url>
   ```

   (Or set `CC_METRICS_SHARE_URL=https://<leaderboard-url>` in your environment.)

2. Enter the emailed code and the name to show on the board:

   ```
   /token-metrics:join verify <code> <Your Name>
   ```

3. Optionally, check exactly what will be sent before anything is synced:

   ```
   /token-metrics:share preview
   ```

Joining syncs your existing history. That history sets your baseline and earns the **First Sync** badge, but
points only count from the week you join.

### Step 2: earn points every week

| Do this | Points |
|---|---|
| Use Claude Code at least once in the week (synced automatically) | +10 |
| Keep the plugin loaded so 80%+ of the week's sessions have hook data | +10 |
| Start tasks with a tag, e.g. `[bugfix] the parser drops time zones` | +2 each, max 20 |
| Rate tasks when done, e.g. `rate 3 ok` (costs no tokens) | +3 each, max 30 |
| Leak less than your baseline (weeks with 3+ active days) | +1 per % below baseline, max 50 |

A week can earn at most **120 points**. Syncing happens in the background at the end of each session, at most once an hour.

To earn improvement points, cut your biggest leaks. Run `/token-metrics:leak-report` to see which ones cost you the
most, and `token-leak-categories.md` for what each one means.

### Step 3: level up, keep streaks, collect badges

- **Levels** come from total points: Rookie (0), Apprentice (50), Practitioner (150), Optimizer (300),
  Specialist (500), Expert (800), Master (1,200), Grandmaster (1,700), Legend (2,300), Mythic (3,000).
- **Streaks** count consecutive active weeks. A week without activity yet doesn't break the streak until it ends.
- **Badges:**

  | Type | Badges |
  |---|---|
  | Participation | First Sync, Fully Hooked (a week with 80%+ hooked sessions), Tagger (50 tagged tasks), Honest Rater (25 rated tasks) |
  | Efficiency | Leak Plugger (a week 25%+ below baseline), Cache Keeper (expired-cache leak under 2% of a week's spend), Lean Start (starting context below the company median) |
  | Consistency | On a Roll (4-week streak), Unstoppable (12-week streak) |
  | Volume (cosmetic, no points) | 100M Club, Billionaire, Token Titan, Centurion, Lifer |

### Step 4: check your progress

```
/token-metrics:share                        # sync now; shows points, level, rank, badges and the badges you're closest to
/token-metrics:leaderboard week             # this week's board (also: month, all)
```

You can also sign in on the leaderboard website with your company email.

### Step 5: share your card (optional)

`/token-metrics:share` prints your public card link, `/u/<handle>`. Posting it on LinkedIn or X shows a preview
image with your name, level, badges, streak, tokens, hours and spend. Choose what it shows:

```
/token-metrics:share card --hide spend,name
/token-metrics:share card --show spend
```

### Leaving

`/token-metrics:share leave` deletes all your data from the server and stops syncing.

## Troubleshooting

- **Empty or tiny report:** check that `~/.claude/projects/` has `.jsonl` transcripts in the date range, or widen `--days`.
- **No task categories or ratings:** the plugin was not loaded for those sessions. Check that
  `~/.claude/metrics/events.jsonl` exists and is growing.
- **Slash command can't find a script:** start a new session so the hook copies the scripts to `~/.claude/metrics/`,
  or run them from the repo as in Option A.
- **`no leaderboard URL configured`:** pass `--url https://<leaderboard-url>` to `/token-metrics:join`, or set
  `CC_METRICS_SHARE_URL`.
