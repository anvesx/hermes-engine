# Gamification

How the token-metrics leaderboard turns Claude Code usage into points, levels, streaks, badges and share cards. All rules live in `leaderboard/lib/score.ts`, and scores are recomputed from stored weekly stats on every request. Changing a rule there takes effect immediately, including for past weeks, with no plugin update.

## Core idea

The aim is to reward people for **using the plugin well** and **leaking fewer tokens over time**. It does not reward using Claude Code more.

- **Points** come from participation and from improvement against your own baseline.
- **Volume** (tokens, API-equivalent spend, active hours) is shown on the leaderboard and cards and earns cosmetic badges. It **never** earns points. If it did, the heaviest spenders would win a game meant to reduce waste.
- **Improvement** is measured against your own baseline, not other people's. Someone doing heavy refactoring and someone answering quick questions can both score well.

## Points (per week)

A week counts once it has at least one session. Points are only awarded from the week you joined onward. History synced when you join sets your baseline but earns nothing.

| What | Points | Rule |
|---|---|---|
| Active week, synced | **+10** | Any week with at least one session |
| Fully hooked | **+10** | Hook data on 80%+ of the week's sessions |
| Tagged tasks | **+2 each, max 20** | Prompts starting with `[category]`, e.g. `[bugfix] ...` |
| Rated tasks | **+3 each, max 30** | `rate 3 ok` after a task |
| Improvement | **+1 per % below baseline, max 50** | See below |

**The most a single week can earn is 120 points.**

### Improvement

- **Waste index:** the sum of each non-review leak category's share of spend for the week. Categories overlap, so it can go above 1. It's only ever compared with your own numbers.
- **Baseline:** the median waste index of your first two weeks with 3 or more active days. These are usually weeks from the history synced when you joined.
- **Points:** each later week with 3 or more active days earns `(baseline − this week) / baseline × 100`, rounded, between 0 and 50. Baseline weeks themselves earn no improvement points.

Example: your baseline is 0.85 and this week's waste index is 0.81. That's 4.7% lower, so you get **+5**.

## Levels

Levels come from total points.

| Level | Title | Points |
|---|---|---|
| 1 | Rookie | 0 |
| 2 | Apprentice | 50 |
| 3 | Practitioner | 150 |
| 4 | Optimizer | 300 |
| 5 | Specialist | 500 |
| 6 | Expert | 800 |
| 7 | Master | 1,200 |
| 8 | Grandmaster | 1,700 |
| 9 | Legend | 2,300 |
| 10 | Mythic | 3,000 |

## Streaks

- **Current streak:** consecutive active weeks ending this week. If the current week has no activity yet, the count ends last week, so a streak doesn't break on Monday morning.
- **Best streak:** the longest run of consecutive active weeks ever. Streak badges use the best streak.

Streaks count all synced history, including weeks from before you joined.

## Badges

| Badge | How to earn it | Type |
|---|---|---|
| First Sync | Join the leaderboard | Participation |
| Fully Hooked | A week (after joining) with hook data on 80%+ of sessions | Participation |
| Tagger | 50 tagged tasks | Participation |
| Honest Rater | 25 rated tasks | Participation |
| Leak Plugger | A week 25%+ below your own baseline waste index | Efficiency |
| Cache Keeper | A week with 3+ active days where "Cache expired after a break" (leak #4) cost under 2% of spend | Efficiency |
| Lean Start | A week with 3+ active days where "Heavy starting context" (leak #1) was below the company median over the last 4 weeks | Efficiency |
| On a Roll | 4-week streak | Consistency |
| Unstoppable | 12-week streak | Consistency |
| 100M Club | 100M tokens | Volume (cosmetic) |
| Billionaire | 1B tokens | Volume (cosmetic) |
| Token Titan | 10B tokens | Volume (cosmetic) |
| Centurion | 100 active hours | Volume (cosmetic) |
| Lifer | 500 active hours | Volume (cosmetic) |

`/token-metrics:share` and the leaderboard's "Next up" panel list the badges you're closest to, with progress such as `4.3B/10.0B tokens`.

## Leaderboard

- **Periods:** this week, the last 4 weeks, and all time. For a period, points are the sum of the points earned in its weeks.
- **Ranking:** by points, then current streak, then name. Tied points share a rank.
- **Columns:** rank, name, level, points, streak, badge count, plus volume (tokens, active hours, spend) for context.
- **Access:** sign-in with a company email is required. Your own row is highlighted.

## Share cards

- `/token-metrics:share` prints a public link, `/u/<handle>`. Posting it on LinkedIn or X shows a 1200×630 card image.
- The card can show: name, level, badges (up to 6), week streak, total tokens, active hours, and API-equivalent spend.
- Every field is on by default. Hide any of them with `/token-metrics:share card --hide spend,name`, and bring them back with `--show`.
- All-time volume is the larger of two numbers: the sum of all stored weeks, and the latest lifetime total from the plugin. Claude Code deletes local transcripts after about 30 days, but the server keeps every week it has received, so totals keep growing.

## Company view (`/admin`)

Admins (set in `ADMIN_EMAILS`) see:
- Active players, spend, tokens, hours, hook coverage, and tagged and rated counts for the last 4 weeks.
- Adoption week by week over the last 8 weeks.
- The biggest leaks across the company, weighted by spend.
- Who hasn't synced in 7 days.
- A CSV export of every user and week.

## Anti-gaming

Users report their own stats, so the server can only check that the numbers are plausible. `leaderboard/lib/validate.ts`:
- **Drops** unknown fields and invalid leak categories.
- **Rejects** negative or out-of-range numbers (for example more than 7 active days or 168 hours in a week), weeks in the future, and impossible counts (more tagged tasks than tasks, more hooked sessions than sessions).
- **Caps** tagging and rating points per week, so spamming either one earns at most 50 points a week.

Someone determined to fake their numbers still could. Treat the leaderboard as a game, not an audit.

## Ideas not built yet

- Team leaderboards and team-vs-team weekly challenges.
- A weekly Slack digest: top movers, new badges, and the company's biggest leak of the week.
- Seasonal resets, such as quarterly seasons with an all-time hall of fame.
- Badges tied to specific leaks, such as a week without "Sessions that never end" (#8) or without "No clear direction" (#9).
- Rewarding streaks of rated tasks with outcome `ok`.
