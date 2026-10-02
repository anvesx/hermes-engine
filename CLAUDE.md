# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A single Claude Code plugin, `plugins/token-metrics/`. It measures Claude Code token use per task and ranks "token leaks" by estimated cost. Everything is plain Python 3 with only the standard library. There is no build step, no dependencies, no test suite and no linter config.

`token-leak-categories.md` at the root is the reference doc for every leak category: what it catches, how it is detected, which canvas rows it merges, and ideas not built yet. It mirrors the team's Slack "Leak Categories" canvas.

## Running

The scripts read real data from `~/.claude/projects/*.jsonl` (Claude Code transcripts) and `~/.claude/metrics/events.jsonl` (hook events). Run them straight from the repo to test changes:

```bash
python3 plugins/token-metrics/scripts/leak_report.py --days 30            # 50 curated categories
python3 plugins/token-metrics/scripts/leak_report.py --days 30 --all      # full canvas list (core + A rows)
python3 plugins/token-metrics/scripts/leak_report.py --all --core         # core leaks only
python3 plugins/token-metrics/scripts/leak_report.py --since 2026-09-01 --ttl 5m --md out.md
python3 plugins/token-metrics/scripts/analyze.py --since 2026-10-01 --csv tasks.csv
```

`--ttl 5m` is for API-key and usage-credit users (5-minute cache, 1.25x write cost). The default `1h` is for subscriptions (2x write cost). `--root` and `--events` override the input paths.

To test the hook, pipe a hook payload into it. Set `CC_METRICS_DIR` so it writes to a scratch directory instead of `~/.claude/metrics`:

```bash
echo '{"hook_event_name":"UserPromptSubmit","session_id":"x","prompt":"rate 3 ok"}' | CC_METRICS_DIR=/tmp/m python3 plugins/token-metrics/scripts/metrics_hook.py
```

## Architecture

**Data flow.** `hooks/hooks.json` points every hook event (SessionStart, UserPromptSubmit, Pre/PostToolUse, PostToolUseFailure, PreCompact, Stop, SessionEnd) at one script, `metrics_hook.py`. The hook appends one JSON line per event to `events.jsonl`. The report scripts read that file together with the transcripts Claude Code already writes, so most leaks are detected from existing history with no hook data. Hook data adds the extras: task categories, ratings and idle detection.

**The hook must never break Claude Code.** It catches every exception and always exits 0. It handles two user commands itself:
- `rate N [ok|partial|fail]` returns `decision: block`, so the prompt never reaches the model.
- A `[category]` prefix tags the start of a new task.

Prompt text is not stored unless `CC_METRICS_KEEP_PROMPTS=1`.

**Script sync.** On SessionStart, the hook copies `analyze.py`, `leak_report.py`, `leak_extra.py` and `leak_categories.py` into `~/.claude/metrics/`. On other events it only copies them if they are missing. The slash commands in `commands/*.md` run the copies from that fixed path, and fall back to `find`-ing them under `~/.claude/plugins`. This means:
- The report scripts must work standalone from a flat directory, importing each other as siblings (`import leak_extra`).
- A new report module has to be added to the list in `sync_report_scripts()`.

**Three layers of leak definitions:**
1. `leak_report.py` holds the `Session` transcript parser, the cost model and the **core leaks**. They are keyed by integer id in `LEAKS` (1–25; ids 23–25 are the 4a–4c breakdowns, see `PARENT`) and detected in `analyse()` and `cross_session()`.
2. `leak_extra.py` holds the canvas's **additional categories** ("A rows") in `ADDITIONAL`. Each one is measured, aliased to a core leak (`SAME_AS`), or given an "unmeasurable" reason. Their finding keys are `lid(n) = 1000 + n`, which keeps them apart from core ids in the shared `findings` dict.
3. `leak_categories.py` defines the **50 curated categories** that the default report shows. Each sums a list of finding keys, mixing core ids and `lid(...)`. Category numbers are fixed even though the table re-sorts by cost on every run.

Detectors call `add_finding(...)` / `add(...)`:
- `ref` identifies the tool result a finding is about. `merged_items()` uses it to count a result once when two detectors in the same curated row flag it.
- `overlap=True` keeps a finding for `--all` but leaves it out of the curated rows.
- Keys starting with `_` in `findings` (`_sessions`, `_prefix_sizes`, …) hold aggregate stats used in notes. They are not leaks.

**Cost model.** Per-call token counts come from transcript `usage` and are exact. The size of individual items is estimated at 4 chars/token; images use their pixel dimensions. A leaked item is charged at the cache-read price on every later call that re-reads it, until the next compaction. Prices are API list prices.

## Keeping things in sync

- Some definitions are copied, not shared, because each script must run alone:
  - `PRICES` appears in both `leak_report.py` and `analyze.py`.
  - `CORRECTION_RE` and `TAG_RE` appear in both `metrics_hook.py` and `leak_report.py`.
  
  Change every copy together.
- When you add, rename or merge a leak or category, update `token-leak-categories.md` to match. Commits so far also bump `version` in `.claude-plugin/plugin.json` and update `plugins/token-metrics/README.md` when the user-facing behaviour changes.
- `scripts/__pycache__/` is committed by accident (there is no `.gitignore`). Don't add new `.pyc` changes to commits.
