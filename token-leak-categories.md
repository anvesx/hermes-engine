# Token Leak Categories

Reference for the `token-metrics:leak-report` categories: what each one catches, how it could be detected, and proposed new categories.

> Note: descriptions of existing categories are inferred from the report output, not from the plugin source.

---

## Current report snapshot (2026-09-01 to 2026-10-01)

156 sessions, API-equivalent spend **$1,609.63**

| # | Leak | Est. cost | Share of spend | Instances | Note |
|---|---|---|---|---|---|
| 2 | Heavy starting context | $413.49 | 25.7% | 149 | median starting context ~162,239 tokens |
| 6 | Losing the cache | $208.94 | 13.0% | 83 |  |
| 7 | Many agents | $172.02 | 10.7% | 26 | spend to review, not all waste |
| 1 | Sessions that never end | $118.09 | 7.3% | 71 | 4 compactions |
| 3 | No clear direction | $90.83 | 5.6% | 37 |  |
| 5 | Bigger model than needed | $56.72 | 3.5% | 1457 |  |
| 4 | Too much tool output | $7.61 | 0.5% | 134 |  |
| 10 | Wordy responses | $0.18 | 0.0% | 4 | all output is 8.5% of spend |
| 8 | Retry loops | $0.00 | 0.0% | 0 |  |
| 9 | Usage while idle | $0.00 | 0.0% | 0 |  |
| 11 | No visibility | $0.00 | 0.0% | 0 | 1/156 sessions have hook data |

Costs overlap, so they don't add up to the total.

---

## Existing categories

| # | Category | What it catches | Detection signal |
|---|---|---|---|
| 1 | **Heavy starting context** | Sessions whose very first call already carries a large prompt: system prompt, tool definitions, memory, CLAUDE.md. That cost repeats on every call. | Token count of the first request, multiplied by the number of calls (e.g. "~361k tokens over 231 calls") |
| 2 | **Sessions that never end** | One session reused for unrelated tasks, so a new task carries all the old context with it | A new task after a gap (30+ min) that still carries the prior context; compaction count |
| 3 | **Losing the cache** | Breaks long enough for the prompt cache to expire, so the next call rewrites the whole context at full write price | Gap between calls longer than the cache TTL, plus tokens rewritten after it (e.g. "717k tokens rewritten, break of 7445 min") |
| 4 | **Many agents** | Heavy use of subagents, each with its own context and calls. Not always waste. | Helper-agent call count and the share of session cost spent in subagents |
| 5 | **No clear direction** | Long exploration before any change is made, usually because the task or target files weren't clear up front | Number of reads/searches before the first edit (e.g. "197 reads/searches") |
| 6 | **Bigger model than needed** | Opus used where Sonnet or Haiku would do, mostly helper agents doing searches or simple tasks | Subagent and helper calls running on the top-tier model |
| 7 | **Too much tool output** | Single tool results large enough to bloat context for the rest of the session | Tool result size above a threshold (e.g. Figma `get_design_context` at ~17–19k tokens) |
| 8 | **Wordy responses** | Output tokens spent on long replies or on rewriting whole files where an edit would do | Full-file `Write` on files that already exist, and long assistant messages |
| 9 | **Retry loops** | The same failing action repeated with little or no change | Consecutive near-identical tool calls that keep returning errors |
| 10 | **Usage while idle** | Tokens spent while no one is at the keyboard: background loops, monitors, scheduled wakeups | Activity with no user input for an extended period (needs hook data) |
| 11 | **No visibility** | Sessions with no hook data, so the report can't categorize them, collect ratings, or detect idle time | Share of sessions that have hook data |

---

## Proposed new categories

### Context that loads before any work starts

| Category | What it catches | Detection signal |
|---|---|---|
| **MCP tool schema bloat** | Connected servers whose tool definitions get sent on every call (the Vercel MCP alone is tens of thousands of tokens) | Tokens taken by tool definitions in the system prompt; servers loaded but never called in the session |
| **Unused skills/plugins** | Skill and plugin listings injected but never invoked | Skills listed vs. `Skill` calls made |
| **Memory/CLAUDE.md bloat** | Large instruction files loaded every session | Size of injected `CLAUDE.md` and memory content |
| **Wrong working directory** | Sessions started from `~` instead of the project, so there's no project scoping and searches run across the whole home dir | Session cwd = home dir combined with broad `find`/`grep` |

### Reading too much

| Category | What it catches | Detection signal |
|---|---|---|
| **Duplicate reads** | Reading the same file several times in one session | Same path in `Read`/`cat` more than once with no edit in between |
| **Whole-file reads** | Reading a full file when only a slice was needed | `Read` with no offset/limit on files over ~500 lines |
| **Generated/vendor files** | Reading lockfiles, `node_modules`, `.pbxproj`, minified JS, build output | Path matches |
| **Large pastes** | Logs or code pasted straight into the prompt | User message token size |

### Images and browser work

| Category | What it catches | Detection signal |
|---|---|---|
| **Screenshot accumulation** | Every screenshot (Figma, Chrome, simulator) stays in context for the rest of the session | Count and token size of image blocks |
| **Full-page dumps** | `read_page` (whole accessibility tree) or `get_page_text` when a targeted `find` would do | Tool name plus result size |
| **Figma over-fetching** | Calling `get_design_context` on large parent frames instead of specific child nodes | Node size and repeated calls on the same file |

### Agents

| Category | What it catches | Detection signal |
|---|---|---|
| **Fork context duplication** | Forked subagents inherit the full parent context, so each one starts at 160k+ | Starting context of each subagent |
| **Overlapping agents** | Parallel agents reading the same files | File-read overlap between sibling agents |
| **Verbose agent reports** | Large subagent results pulled back into the main context | Size of agent result |

### Wasted or repeated work

| Category | What it catches | Detection signal |
|---|---|---|
| **Abandoned sessions** | Spend that ends with no edits, commits, or deploys | Sessions with zero write actions |
| **Repeated tasks across sessions** | The same request redone in several sessions | Similar first prompts in the same project |
| **Failed/denied tool calls** | Schema errors, permission denials, wrong IDs (common with MCP tools) | Error results and the retries after them |
| **Polling** | Repeatedly checking deploy, build, or CI status | Same read-only tool called N times in a row |
| **Noisy commands** | Build or install output dumped in full (`xcodebuild`, `npm install`, `pod install`) | Size of Bash output, by command |

### Model and cache settings

| Category | What it catches | Detection signal |
|---|---|---|
| **High effort on trivial turns** | Long thinking on simple requests | Ratio of thinking tokens to output |
| **Cache busts from config changes** | Switching models or toggling MCP servers mid-session, which rewrites the whole prefix | Model or tool-list changes inside one session |
| **Compaction cost** | Writing the summary, then re-reading everything after it | Tokens around each compaction event |

---

## How new categories relate to existing ones

- **#1 Heavy starting context → MCP schema bloat, unused skills, memory bloat, wrong working directory.** These split #1 by source, so it shows *why* the starting context is heavy, not just that it is.
- **#3 Losing the cache → cache busts from config changes.** #3 only catches cache expiry from time gaps. Switching models or toggling MCP servers mid-session busts the cache with no gap at all.
- **#7 Too much tool output → screenshots, full-page dumps, noisy commands, Figma over-fetching.** These split #7 by source. Images in particular probably aren't counted as "tool output" today.
- **#9 Retry loops → failed/denied tool calls.** #9 shows 0 instances, so it may only catch exact repeats. The new category would also catch retries that change slightly after a schema error or permission denial.
- **#4 Many agents → fork context duplication, overlapping agents, verbose agent reports.** These show which part of agent spend is waste.
- **#10 Usage while idle reads $0** only because there's no hook data (#11). Fixing #11 is what makes #10 and the session categories work.

---

## Where to start

1. **MCP schema bloat** and **wrong working directory**: probably a large part of the $413 "Heavy starting context" row. Disconnecting rarely used MCP servers could cut every call.
2. **Screenshot accumulation** and **Figma over-fetching**: the mobile/Figma sessions (BIT-landers-nsf-mobile) appear at the top of several leak rows.
3. **Fork context duplication**: multiplies the starting-context problem inside the $172 "Many agents" row.
4. **Enable hooks (#11)**: unlocks idle detection and per-session categorization.
