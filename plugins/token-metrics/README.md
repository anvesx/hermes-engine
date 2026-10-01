# token-metrics plugin

Measures every Claude Code task (tokens, cost, latency, frustration, outcome) by category, and ranks
token leaks by estimated cost, using the categories from the team's Leak Categories canvas
(see `token-leak-categories.md` at the repo root). Your settings.json hooks are not modified: plugin hooks run
alongside your own. All data stays in `~/.claude/metrics/`.

## Use

| Type in Claude Code | What happens |
|---|---|
| `[bugfix] the parser drops time zones` | Starts a task in category `bugfix` (the prompt goes to Claude as normal) |
| `rate 3 ok` | Frustration 1-5 and outcome ok / partial / fail for the task just done. Blocked by the hook, so it costs no tokens |
| `/token-metrics:leak-report` | Leak report for the last 30 days (uses a few thousand tokens to display) |
| `/token-metrics:task-report` | Metrics by category |

Free alternative from a terminal:

```bash
python3 ~/.claude/metrics/leak_report.py --days 30 --md leak_report.md
python3 ~/.claude/metrics/analyze.py --csv tasks.csv
```

The scripts are copied to `~/.claude/metrics/` at the start of each session, so this path stays
valid after plugin updates. Add `--core` to skip the additional-categories table, and `--ttl 5m` to the leak report if you use an API key or usage credits.

## Privacy

Prompt text is not stored, only length, category and whether it looked like a correction.
Set `CC_METRICS_KEEP_PROMPTS=1` to keep the first 500 characters.
