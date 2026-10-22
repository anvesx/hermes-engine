# Leak categories that are vague or measured wrongly

A review of 18 curated leak categories (see `category-calculation-logic.md` for how each is calculated), ranked worst first. Data checks use one developer's last 30 days of transcripts, run on 2026-10-22.

## Measured wrongly or labelled misleadingly

### 1. 05 Many agents is not a leak at all
It counts every dollar spent on helper agents, with nothing subtracted. Using agents well is often how you *save* money, because work done in an agent keeps the main chat small. As it stands, the most "efficient-looking" user is one who never delegates.

The real waste inside agent use already has its own rows (13 Fork context duplication, 31 Duplicate reading across agents, 42 Verbose agent reports and briefs).

**Suggested fix:** relabel the row "Agent spend" and keep it off any ranking of leaks.

### 2. 03 Cold cache at start charges for something you can't avoid
Every new chat has to load its setup once. That is the price of starting, not waste. The row charges the *full* cost of that first load, when at most the caching surcharge on it is arguably avoidable. It also counts the same setup tokens that 01 Heavy starting context already counts.

**Suggested fix:** charge only the surcharge, or treat it as spend rather than a leak.

### 3. 02 Cache-write premium counts the cost of a discount as a leak
Caching costs a little extra once and then makes every later re-read about 10 times cheaper. Without caching the bill would be higher, not lower. Showing it as a top "leak" invites the wrong conclusion.

What *is* worth tracking is caches that get rebuilt again and again, and 04 Cache expired after a break and 16 Model switch rewrote the cache already cover that.

**Suggested fix:** relabel or hide it from the leak ranking.

### 4. 10 Restarting too often contradicts other rows and has a bug
- **Contradiction:** 06 and 08 charge you for staying in one long chat. 10 charges you for starting a new one within an hour. A user can't satisfy both.
- **Bug:** it compares when a chat started with when the *previous* chat ended. Two chats running on the same project at the same time get the second flagged as a restart. In the sample data, **10 of the 27 "restarts" were exactly this**: the earlier chat was still running.

**Suggested fix:** skip chats that start before the previous one ended, and reconcile the rule with 06 and 08.

### 5. 12 Bigger model than needed doesn't measure what its name says
It's meant to catch the top model used on simple tasks, but it only knows a task is simple if the user tags it (`[docs]`, `[chore]`, …). Almost nobody tags. In the sample data, **0 findings came from tagged tasks and all 681 came from helper agents running on Opus**. So it really means "helper agents ran on Opus", and it assumes Sonnet would have done the same work equally well.

**Suggested fix:** rename it to reflect what it measures, or find a way to judge task difficulty without tags.

## Vague: the idea is fine, the rule is crude

### 6. 26 Repeated tasks across sessions
- Two chats count as the same task if their opening messages share about 60% of their words. Recurring work like "review this PR" or "continue the migration from yesterday" matches easily.
- When it matches, the **entire** chat's cost is charged, not just the repeated part.
- It compares against every earlier chat in the project, with no time limit.

### 7. 06, 08, 11 and 17 measure the same thing four ways
Together they made up about 42% of spend in the sample, and they all price "old conversation being re-read".
- **06** charges length above a fixed line.
- **08** charges leftovers from an earlier task. Since nobody tags, a "new task" in practice means "you came back after 30 minutes away", so a lunch break mid-task counts as a task switch.
- **11** calls a tool result stale after 30 more messages. Claude can send 30 messages in a few minutes, while the file it read is still being edited.
- **17** has no threshold at all: every reply Claude ever wrote counts once it's re-read. That is really just the cost of having a conversation.

The real signal ("chats run too long") is valid, but it's inflated by counting it four times.

**Suggested fix:** show these as one "long conversations" figure.

### 8. 09 No clear direction
More than 15 lookups before the first code change is called "wandering". Careful debugging gets penalised, and a task that only investigates and never edits is never counted at all.

### 9. 07 Interrupted turns
Hitting stop is often the *right* call, because it cuts off a wrong path early. The row charges the whole turn as waste, even though part of that work usually stays useful.

## Reasonably sound

- **04 Cache expired after a break:** a real, avoidable cost, measured fairly.
- **13 Fork context duplication**
- **14 Large tool-call arguments**
- **20 Visual iteration loops**
- **24 Too much tool output:** crude thresholds, but they point at real behaviour.

### 01 Heavy starting context
Measured correctly, and the sample data was surprising. Across 132 chats, the *median* chat already carried about **360,000 tokens on its very first message**. The smallest was about 53,000, and chats with a single message were still that large. That is far more than CLAUDE.md alone would explain. The cause isn't confirmed; connected tools and plugins are the likely place to look. This may be the single biggest real lever, and it also inflates 02 and 03.

## Bottom line

Roughly 60% of the listed percentage comes from rows that are either not waste (05, 02, 03) or counted several times over (06, 08, 11, 17). If the dashboard is driving team behaviour, fix three things first:

1. Relabel or hide 05, 02 and 03.
2. Fix the bug in 10 that flags parallel chats as restarts.
3. Show 06, 08, 11 and 17 as one "long conversations" figure.
