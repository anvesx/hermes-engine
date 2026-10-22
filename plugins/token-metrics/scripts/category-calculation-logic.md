# How the leak categories are calculated

A plain-English explanation of how 18 of the curated leak categories are measured, written for readers who don't need the formulas. Each category's code location is given so engineers can check the details.

## One idea first

Claude has no memory between messages. Every time it replies, it re-reads the **whole conversation so far**: its instructions, every file it opened, every earlier reply. Re-reading old material is cheap per message, but it is paid again on every message, so it adds up.

Most categories ask one question: **"What was Claude re-reading that it probably didn't need, and how many times did it re-read it?"** The rest ask: **"What work was wasted or redone?"**

"Review" means the number is worth looking at but isn't all waste.

## What the percentages mean

Each percentage is **that category's cost ÷ total spend** (main chat plus helper agents) over the period. On the leaderboard, weeks are combined weighted by each week's spend.

**The categories overlap.** One long chat can show up in 06, 08, 11 and 17 at once, so the percentages add up to more than 100%. Use them to see **where to look**, not as slices of a pie.

---

## Conversation history

### 06 Long history replay (review)
`leak_extra.py`, A1

Once a conversation passes a set size (100,000 tokens, roughly a long book chapter), every extra message pays to re-read everything above that line. We add up that extra over every message. It doesn't matter whether the work was one task or ten. Long chats cost more.

### 08 Sessions that never end
`leak_report.py`, core leak #2

We spot when someone finishes one task and starts a new one in the same chat: they type a tag like `[bugfix]`, or come back after 30+ minutes away. If a lot of the old task's history (over 20,000 tokens) is still in the chat, we charge for re-reading it on every message of the new task. The fix is to start a fresh chat for new work.

### 11 Stale tool results carried forward
`leak_extra.py`, A5

When Claude reads a file or runs a command, the output stays in the chat. Once 30 more messages have passed and it's still there, we assume it's no longer useful. From that point on, every message that re-reads it is counted.

### 17 Old replies replayed (review)
`leak_extra.py`, A6

Claude's own earlier explanations stay in the chat and get re-read on every later message. We count that cost. Useful context is part of it, so it's not all waste.

### 26 Repeated tasks across sessions (review)
`leak_report.py`, core leak #15

Within one project, if a new chat opens with almost the same request as an earlier chat (about 60% of the same words), we count the whole new chat as a likely repeat. This often means the first attempt didn't finish the job or the result wasn't saved.

### 10 Restarting too often
`leak_extra.py`, A10

If someone starts a new chat within an hour of closing the last one, Claude has to re-learn the project before doing real work. We count everything it spent before its first actual code change.

## Starting context

### 01 Heavy starting context
`leak_report.py`, core leak #1

Before anyone types a word, every chat already loads instructions, tool lists, project notes and memory. A modest amount (10,000 tokens) is fine. Anything above that baseline is charged on **every message** of the chat, because it's re-read each time. Big setup files make every message more expensive.

## Prompt cache

Claude's provider keeps recently read material in a short-term "cache" so re-reading it is cheap. Putting material into the cache costs extra (1.25x the normal price for a 5-minute cache, 2x for a 1-hour cache), and the cache expires after a period of inactivity.

### 02 Cache-write premium (review)
`leak_extra.py`, A37

Every time material goes into the cache, there's a surcharge over the normal price. We add up all those surcharges. It's the normal cost of caching and usually pays for itself, but it grows when the cache keeps getting rebuilt.

### 03 Cold cache at session and agent start (review)
`leak_extra.py`, A22

Every new chat, and every helper agent, starts with an empty cache and has to fill it from scratch. We count that first fill. More chats and more agents mean more cold starts.

### 04 Cache expired after a break
`leak_report.py`, core leak #3a

Someone steps away long enough for the cache to expire (typically an hour) and then continues. Claude has to rebuild the whole conversation in the cache at full price. We count the difference between that rebuild and what a normal cheap re-read would have cost.

## Agents

### 05 Many agents (review)
`leak_report.py`, core leak #4

Claude can hand work to helper agents, each running its own separate conversation. This row is simply **everything spent on helper agents**. Agents are often worth it, so treat it as "how much we rely on them", not waste.

### 13 Fork context duplication
`leak_report.py`, core leak #4a

Some helper agents start with a large copy of the main conversation (over 50,000 tokens) instead of a short brief. When an agent starts that heavy, we charge for re-reading that inherited bulk on every message the agent sends.

## Exploration and retries

### 09 No clear direction
`leak_report.py`, core leak #5

For each task, we count how many times Claude searched or opened files before making its first change. Some looking around is normal. Past 15 lookups we count the extra searching as wandering, usually a sign the request was vague.

### 07 Interrupted turns
`leak_extra.py`, A134

When someone hits stop partway through Claude's answer, everything Claude spent on that answer is counted as wasted.

## Model choice

### 12 Bigger model than needed
`leak_report.py`, core leak #6

For tasks tagged as simple (docs, explanations, questions, renames, chores, commits), and for every helper agent, we check whether the most expensive model (Opus or Fable) was used. If it was, we count how much cheaper the same work would have been on Sonnet.

## Tool output and images

### 14 Large tool-call arguments
`leak_extra.py`, A66

Sometimes Claude sends a very large block of text (over 1,000 tokens) to a tool, such as a long command or a big search query. It pays once to write it and again every time it's re-read later. We count both. File edits and agent hand-offs are excluded.

### 24 Too much tool output
`leak_report.py`, core leak #7

When reading a file or running a tool returns a very large result (over 4,000 tokens), we treat the first 2,000 tokens as useful and count the re-reading of the rest. Huge files and unfiltered results drive this. Terminal output, repeat reads and dependency folders are counted in other rows.

### 20 Visual iteration loops
`leak_report.py`, core leak #21

In design or UI work, Claude often makes a change, takes a screenshot, and repeats. The first three rounds per task are free. From the fourth round on, we count each extra round as trial-and-error.
