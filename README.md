# Token Metrics for Claude Code

See where your Claude Code tokens go. Token Metrics tracks your token usage, time and cost per task, finds "token
leaks" (context and work you pay for without needing it) and shows it all on a personal dashboard.

## Requirements

- Python 3 (standard library only, nothing to install)
- Claude Code
- A `@devxlabs.ai` email address

## Get started

1. **Install the plugin.** One command in a terminal:

   ```bash
   claude plugin marketplace add anvesx/hermes-engine && claude plugin install token-metrics@hermes-engine
   ```

   Then start a new Claude Code session. The plugin loads in every session and doesn't change your `settings.json`.

   Or, from inside a Claude Code session:

   ```
   /plugin marketplace add anvesx/hermes-engine
   /plugin install token-metrics@hermes-engine
   /reload-plugins
   ```

2. **Make sure git knows your work email.** The plugin joins you with it, so there's no code to type:

   ```bash
   git config --global user.email   # should print you@devxlabs.ai
   git config --global user.name    # the name shown on the leaderboard
   ```

   If it prints something else, set it with `git config --global user.email you@devxlabs.ai`.

3. **Connect your account.** In Claude Code, run:

   ```
   /token-metrics:dashboard
   ```

   It joins with your git email and name, syncs your history and opens your dashboard in the browser, already
   signed in. It prints who you joined as; if that's wrong, run `/token-metrics:join you@devxlabs.ai`.

4. **Work as usual, and label your tasks.** Start a task with a category in brackets, and rate it when it's done:

   ```
   [bugfix] the parser drops time zones
   rate 3 ok
   ```

   `rate` takes how frustrating the task was (1-5) and how it went (`ok`, `partial` or `fail`). It costs no tokens.

5. **Open your dashboard any time:**

   ```
   /token-metrics:dashboard
   ```

   It syncs your latest numbers first. Your stats also sync on their own at the end of each session, at most once an hour.

You can also do steps 3 and 5 from a terminal, without Claude Code and without using tokens:

```bash
python3 ~/.claude/metrics/share.py dashboard
```

## Your dashboard

- **Token usage:** this week, today, the last 30 days, per active day and all time; tokens per day; what the tokens
  are (input, cache write, cache read, output); tokens by model; and how much went to subagents.
- **Your week:** active hours, API-equivalent spend and waste index, compared with last week and with your own baseline.
- **Trends:** 12-week charts of tokens, hours, spend and waste index.
- **Your biggest leaks**, next to the company average.
- **Your progress:** level, points, streak and badges, and where you stand among your colleagues.

You also get a public card at `/u/<your-handle>` that you can share. It shows your name, level, badges, streak,
tokens, hours and spend; hide any of them with `/token-metrics:share card --hide spend,name`. Only you, signed in,
see the full dashboard at that address.

## Get more out of it

Points and levels follow the habits that make the numbers useful:

- **Keep the plugin loaded** in every session, so all your work is measured.
- **Label your tasks** with `[category]` and **rate them** with `rate N ok|partial|fail`, so you can see which kinds of
  work cost the most.
- **Cut your biggest leaks.** Each week you leak less than your own baseline earns more points. See which leaks cost
  you most with `/token-metrics:leak-report`, and what each one means in [`token-leak-categories.md`](token-leak-categories.md).

Using Claude Code more never earns points; using it with less waste does. The full rules are in [`gamify.md`](gamify.md).

## Reports

| Command | What you get |
|---|---|
| `/token-metrics:dashboard` | Sync and open your dashboard |
| `/token-metrics:leak-report` | Token leaks for the last 30 days, ranked by cost |
| `/token-metrics:task-report` | Tokens, time, frustration and success by task category |
| `/token-metrics:wrapped` | Your usage in numbers: tokens, spend, active hours, streaks, biggest leaks |
| `/token-metrics:share preview` | Exactly what syncing sends; sends nothing |
| `/token-metrics:share leave` | Delete your data from the server and stop syncing |

The same reports run from a terminal and use no Claude tokens:

```bash
python3 ~/.claude/metrics/leak_report.py --days 30 --md leak_report.md
python3 ~/.claude/metrics/analyze.py --csv tasks.csv
python3 ~/.claude/metrics/stats.py
```

## Privacy

Nothing leaves your machine until you connect your account (step 3). After that, only weekly and daily totals are
sent: tokens, spend, hours, task counts and leak shares. Prompts, code, project names and file paths are never sent.
By default, your prompt text isn't stored locally either. `/token-metrics:share leave` deletes everything the server holds about
you. Details are in [`plugins/token-metrics/README.md`](plugins/token-metrics/README.md#privacy).

Joining takes your email from git and doesn't verify it, so someone could join under a colleague's address. That's
accepted for an internal leaderboard. The website's own sign-in page still checks you with an email code.

## Troubleshooting

- **`invalid choice: 'dashboard'`:** your plugin is out of date. Run `claude plugin marketplace update hermes-engine && claude plugin update token-metrics@hermes-engine`, then start a new Claude Code session.
- **"your git email is …":** joining uses `git config --global user.email`. Set it to your work email, or run `/token-metrics:join you@devxlabs.ai`.
- **The dashboard shows zeros:** your stats haven't synced yet. Run `/token-metrics:dashboard` again and check that it
  prints `Synced your latest stats.`
- **The browser shows a sign-in page or only your public card:** the sign-in link expired (it works once, for 5
  minutes), or you opened your card link directly. Run `/token-metrics:dashboard` again.
- **No task categories or ratings:** the plugin wasn't loaded for those sessions. Check that
  `~/.claude/metrics/events.jsonl` exists and grows as you work.
- **A slash command can't find its script:** start a new session so the plugin can set itself up.
- **Empty or tiny leak report:** widen the range, e.g. `--days 90`.

## Report options

`leak_report.py`:

| Flag | Effect |
|---|---|
| `--days N` | Only the last N days |
| `--since YYYY-MM-DD` | Only from this date (instead of `--days`) |
| `--ttl 5m` | Use if you are on an API key or usage credits (5-minute cache). The default `1h` is for subscriptions. Cache writes are priced by the lifetime the transcript records; this is the fallback and sets break detection |
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

## For developers

The repo has two parts: `plugins/token-metrics/` (the plugin and report scripts, plain Python 3) and `leaderboard/`
(the dashboard server, Next.js on Vercel). See [`CLAUDE.md`](CLAUDE.md) and [`leaderboard/README.md`](leaderboard/README.md).
