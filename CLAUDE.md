# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two parts:
- `plugins/token-metrics/` is a Claude Code plugin. It measures Claude Code token use per task and ranks "token leaks" by estimated cost. It is plain Python 3 with only the standard library: no build step, no dependencies, no test suite and no linter config.
- `leaderboard/` is a Next.js app deployed on Vercel. Users opt in and the plugin syncs aggregate stats to it. It scores points, levels, streaks and badges, and serves the internal leaderboard, public share cards and an admin view of company-wide results.

`token-leak-categories.md` at the root is the reference doc for every leak category: what it catches, how it is detected, which canvas rows it merges, and ideas not built yet. It mirrors the team's Slack "Leak Categories" canvas.

## Running

The scripts read real data from `~/.claude/projects/*.jsonl` (Claude Code transcripts) and `~/.claude/metrics/events.jsonl` (hook events). Run them straight from the repo to test changes:

```bash
python3 plugins/token-metrics/scripts/leak_report.py --days 30            # 50 curated categories
python3 plugins/token-metrics/scripts/leak_report.py --days 30 --all      # full canvas list (core + A rows)
python3 plugins/token-metrics/scripts/leak_report.py --all --core         # core leaks only
python3 plugins/token-metrics/scripts/leak_report.py --since 2026-09-01 --ttl 5m --md out.md
python3 plugins/token-metrics/scripts/analyze.py --since 2026-10-01 --csv tasks.csv
python3 plugins/token-metrics/scripts/stats.py [--json]                  # "Wrapped" summary, or the exact sync payload
```

Cache writes are priced by the lifetime each transcript entry records (`usage.cache_creation`: 5m at 1.25x input, 1h at 2x). `--ttl` is the fallback for entries without that split, and sets the cache lifetime used to detect breaks: `5m` for API-key and usage-credit users, the default `1h` for subscriptions. `--root` and `--events` override the input paths.

To test the hook, pipe a hook payload into it. Set `CC_METRICS_DIR` so it writes to a scratch directory instead of `~/.claude/metrics`:

```bash
echo '{"hook_event_name":"UserPromptSubmit","session_id":"x","prompt":"rate 3 ok"}' | CC_METRICS_DIR=/tmp/m python3 plugins/token-metrics/scripts/metrics_hook.py
```

To work on the leaderboard locally, use Postgres and point the plugin at the dev server. Without `SMTP_USER`/`SMTP_PASS`, sign-in codes are printed to the server log:

```bash
cd leaderboard && npm install
DATABASE_URL=postgres://localhost/token_metrics npm run db:init        # applies db/schema.sql (idempotent)
DATABASE_URL=... ADMIN_EMAILS=you@devxlabs.ai npm run dev
CC_METRICS_DIR=/tmp/m CC_METRICS_SHARE_URL=http://localhost:3000 python3 plugins/token-metrics/scripts/share.py join you@devxlabs.ai
npm run typecheck && npm run build
```

Deploy production with `cd leaderboard && npm run deploy`. It typechecks, applies `db/schema.sql` to the production database (pulled with `vercel env pull`), then runs `vercel --prod`. Never run a bare `vercel --prod`: code that needs a new table or column would fail until `db:init` runs.

## Architecture

**Data flow.** `hooks/hooks.json` points every hook event (SessionStart, UserPromptSubmit, Pre/PostToolUse, PostToolUseFailure, PreCompact, Stop, SessionEnd) at one script, `metrics_hook.py`. The hook appends one JSON line per event to `events.jsonl`. The report scripts read that file together with the transcripts Claude Code already writes, so most leaks are detected from existing history with no hook data. Hook data adds the extras: task categories, ratings and idle detection.

**The hook must never break Claude Code.** It catches every exception and always exits 0. It handles two user commands itself:
- `rate N [ok|partial|fail]` returns `decision: block`, so the prompt never reaches the model.
- A `[category]` prefix tags the start of a new task.

Prompt text is not stored unless `CC_METRICS_KEEP_PROMPTS=1`.

**Script sync.** On SessionStart, the hook copies the scripts listed in `sync_report_scripts()` into `~/.claude/metrics/`. On other events it only copies them if they are missing. The slash commands in `commands/*.md` run the copies from that fixed path, and fall back to `find`-ing them under `~/.claude/plugins`. This means:
- The report scripts must work standalone from a flat directory, importing each other as siblings (`import leak_extra`).
- A new report module has to be added to the list in `sync_report_scripts()`.

**Three layers of leak definitions:**
1. `leak_report.py` holds the `Session` transcript parser, the cost model and the **core leaks**. They are keyed by integer id in `LEAKS` (1–26; ids 23–25 are the 4a–4c breakdowns and 26 is 3a, the break-only part of #3, see `PARENT`) and detected in `analyse()` and `cross_session()`.
2. `leak_extra.py` holds the canvas's **additional categories** ("A rows") in `ADDITIONAL`. Each one is measured, aliased to a core leak (`SAME_AS`), or given an "unmeasurable" reason. Their finding keys are `lid(n) = 1000 + n`, which keeps them apart from core ids in the shared `findings` dict.
3. `leak_categories.py` defines the **50 curated categories** that the default report shows. Each sums a list of finding keys, mixing core ids and `lid(...)`. Category numbers are fixed even though the table re-sorts by cost on every run.

Detectors call `add_finding(...)` / `add(...)`:
- `ref` identifies the tool result a finding is about. `merged_items()` uses it to count a result once when two detectors in the same curated row flag it.
- `overlap=True` keeps a finding for `--all` but leaves it out of the curated rows.
- Keys starting with `_` in `findings` (`_sessions`, `_prefix_sizes`, …) hold aggregate stats used in notes. They are not leaks.

**Leaderboard sync.**
- `stats.py` runs the leak detectors once over all history, then splits the results into per-ISO-week buckets using local time:
  - Tokens, spend, active hours and active days go to the week each call happened in.
  - Session and task counts, and the leak shares, go to the week the session started in.
  - Since 1.5.0 each week and the lifetime block also carry `token_split`, `model_tokens` and `agent_tokens`, and the payload has a `days` list (last 56 days of token totals). These are optional in `validate.ts`, so `SCHEMA` stays 1; the server keeps `days` in `users.days`.
- `share.py` holds the user's token in `share.json` (mode 0600). It sends `stats.py`'s payload to `POST /api/sync`.
- On SessionEnd, `metrics_hook.py` starts `share.py sync --background` as a detached process, only if the user has joined and the last sync is over an hour old. The hook itself returns immediately.
- The payload must never contain prompt text, project names, file paths or session ids.

**Leaderboard backend (`leaderboard/`).**
- `lib/validate.ts` keeps only whitelisted, range-checked fields from each payload, because clients report their own numbers. `weekly_stats` stores one row per user and week, replaced on each sync.
- Scoring happens on read, in `lib/score.ts`. `lib/board.ts` scores every player in memory on each request, which is fine at company size. Points:
  - Participation, earned only from the user's join week onward.
  - Improvement against the user's own baseline `waste_index`, taken from their first two weeks with 3+ active days. Usually that's history synced when they joined.
- Volume (tokens, spend, hours) earns cosmetic badges but never points.
- Auth works by email code. `/api/auth/verify` issues a token per sign-in; CLI tokens go in the Bearer header, web tokens in the `tm_session` cookie. Only SHA-256 hashes of tokens and codes are stored.
- Public pages are `/u/[handle]` and `/u/[handle]/card.png`, which renders with `next/og`. They show only the fields enabled in the user's `card_fields`. Everything else requires sign-in. `/admin` is limited to `ADMIN_EMAILS`, and then asks for a shared password (`ADMIN_PASSWORD` in `lib/admin.ts`) once per browser; the `tm_admin` cookie holds its hash for 12 h. `/admin/export` needs both.
- `/u/[handle]` doubles as the owner's dashboard: signed in as that user (and without `?public=1`), it renders `app/u/[handle]/dashboard.tsx` from `lib/dashboard.ts` instead of the public card. `/token-metrics:dashboard` (`share.py dashboard`) gets there by calling `POST /api/auth/link`, which returns a single-use, 5-minute link; `GET /api/auth/link?t=…` spends it, sets the web session cookie and redirects. Links live in the `login_links` table.

**Cost model.** Per-call token counts come from transcript `usage` and are exact. The size of individual items is estimated at 4 chars/token; images use their pixel dimensions. A leaked item is charged at the cache-read price on every later call that re-reads it, until the next compaction. Prices are API list prices per model version (`PRICES`; Opus 4.x and Opus 5.5 differ), matched longest id first; an unlisted version falls back to its family's current model. Entries with model `<synthetic>` are written by Claude Code itself and are skipped.

## Keeping things in sync

- Some definitions are copied, not shared, because each script must run alone:
  - `PRICES` (and the cache-write multipliers) appear in both `leak_report.py` and `analyze.py`. Add new model versions to both.
  - `CORRECTION_RE` and `TAG_RE` appear in both `metrics_hook.py` and `leak_report.py`.
  - `SYNC_EVERY_S` appears in both `metrics_hook.py` and `share.py`.
  - The payload schema is built by `stats.py` and validated by `leaderboard/lib/validate.ts`. Bump `SCHEMA` in both for breaking changes.
  - `leaderboard/lib/categories.json` is generated from `leak_categories.py`. Run `npm run categories` after changing categories.
  
  Change every copy together.
- When you add, rename or merge a leak or category, update `token-leak-categories.md` to match. Commits so far also bump `version` in `.claude-plugin/plugin.json` and update `plugins/token-metrics/README.md` when the user-facing behaviour changes.
- `.gitignore` at the root covers Python caches, `.claude/settings.local.json` and report output. `leaderboard/.gitignore` covers the Node build output.
