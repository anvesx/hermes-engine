# Token Leak Categories

Reference for the `token-metrics:leak-report` categories: what each one catches, how it could be detected, and proposed new categories.

---

## Current report snapshot (2026-09-01 to 2026-10-01)

156 sessions, API-equivalent spend **$1,609.63**. Taken before the categories were updated; rows renumbered to the canvas numbering.

| # | Leak | Est. cost | Share of spend | Instances | Note |
|---|---|---|---|---|---|
| 1 | Heavy starting context | $413.49 | 25.7% | 149 | median starting context ~162,239 tokens |
| 3 | Losing the cache | $208.94 | 13.0% | 83 | included compaction rewrites, now #19 |
| 4 | Many agents | $172.02 | 10.7% | 26 | spend to review, not all waste |
| 2 | Sessions that never end | $118.09 | 7.3% | 71 | 4 compactions (double counted then, now fixed) |
| 5 | No clear direction | $90.83 | 5.6% | 37 |  |
| 6 | Bigger model than needed | $56.72 | 3.5% | 1457 |  |
| 7 | Too much tool output | $7.61 | 0.5% | 134 | included shell output and agent reports, now #17 and #4c |
| 8 | Wordy responses | $0.18 | 0.0% | 4 | all output is 8.5% of spend |
| 9 | Retry loops | $0.00 | 0.0% | 0 |  |
| 10 | Usage while idle | $0.00 | 0.0% | 0 |  |
| 11 | No visibility | $0.00 | 0.0% | 0 | 1/156 sessions have hook data |

Costs overlap, so they don't add up to the total.

---

## Categories in the report

Numbering and categories follow the team's [Leak Categories canvas](https://devxconsultancy.slack.com/docs/T046R1BS75M/F0C61Q25V5J): 1-11 are the core leaks, 12-22 the additional ones, and 4a-4c break down #4.

| # | Leak | Category | What it catches | Detection signal |
|---|---|---|---|---|
| 1 | **Heavy starting context** | Persistent instructions and memory | Sessions whose very first call already carries a large prompt: system prompt, tool definitions, memory, CLAUDE.md. That cost repeats on every call. | First-request context above 10k tokens, re-read on every call |
| 2 | **Sessions that never end** | Conversation history | One session reused for unrelated tasks, so a new task carries all the old context with it | A new task (tag or 30+ min gap) still carrying 20k+ tokens of prior context; compaction count |
| 3 | **Losing the cache** | Cache misses and invalidation | Breaks long enough for the prompt cache to expire, so the next call rewrites the whole context at full write price | Large cache writes after a break, model switch or context change (rewrites after compaction go to #19) |
| 4 | **Many agents** | Multi-agent workflows | Heavy use of subagents, each with its own context and calls. Not always waste. | Helper-agent call count and share of session cost |
| 4a | **Fork context duplication** | Multi-agent workflows | Forked subagents inherit the full parent context, so each one starts at 160k+ | Helper agent whose first call is above 50k tokens; excess re-read on each of its calls |
| 4b | **Overlapping agents** | Multi-agent workflows | Parallel agents reading the same files | A file `Read` by a helper agent after a sibling agent already read it |
| 4c | **Verbose agent reports** | Multi-agent workflows | Large subagent results pulled back into the main context | `Agent`/`Task` result above 2.5k tokens |
| 5 | **No clear direction** | Repository discovery and file reading | Long exploration before any change is made, usually because the task or target files weren't clear up front | More than 15 reads/searches before the first edit |
| 6 | **Bigger model than needed** | Model selection and reasoning | Opus used where Sonnet or Haiku would do, mostly helper agents doing searches or simple tasks | Top-tier model on simple task categories and on helper agents; the note shows the share of main-session spend on Opus/Fable |
| 7 | **Too much tool output** | Tools, MCP, skills, and plugins | Single tool results large enough to bloat context for the rest of the session | Duplicate reads, dependency-folder hits, non-shell results above 4k tokens |
| 8 | **Wordy responses** | Answer and artifact generation | Output tokens spent on long replies or on rewriting whole files where an edit would do | Full-file `Write` on files already read; output share of spend |
| 9 | **Retry loops** | Retries, automation, and context rebuilding | The same failing action repeated with little or no change | The same tool input failing 3+ times |
| 10 | **Usage while idle** | Retries, automation, and context rebuilding | Tokens spent while no one is at the keyboard: background loops, monitors, scheduled wakeups | Turns that started without a typed prompt (needs hook data) |
| 11 | **No visibility** | Observability coverage | Sessions with no hook data, so the report can't categorize them, collect ratings, or detect idle time | Share of sessions with hook data |
| 12 | **MCP tool schema bloat** | Tools, MCP, skills, and plugins | Connected servers whose tool definitions get sent on every call | Not measured yet: transcripts don't record the loaded tool definitions (counted inside #1) |
| 13 | **Unused skills/plugins** | Tools, MCP, skills, and plugins | Skill and plugin listings injected but never invoked | Not measured yet: transcripts don't record the loaded skill listings (counted inside #1) |
| 14 | **Screenshot accumulation** | Images, PDFs, and browser interaction | Every screenshot (Figma, Chrome, simulator) stays in context for the rest of the session | Image blocks in tool results, sized from their pixels, re-read after first use until compaction |
| 15 | **Repeated tasks across sessions** | Conversation history | The same request redone in several sessions | First prompt overlapping 60%+ (by word) with an earlier session in the same project; spend to review |
| 16 | **Failed/denied tool calls** | Retries, automation, and context rebuilding | Schema errors, permission denials, wrong IDs (common with MCP tools) | `is_error` tool results, classified as denied / schema error / wrong id; error text carried plus the wasted call's output |
| 17 | **Noisy commands** | Terminal, build, and test output | Build or install output dumped in full (`xcodebuild`, `npm install`, `pod install`) | `Bash` results above 4k tokens |
| 18 | **High effort on trivial turns** | Model selection and reasoning | Long thinking on simple requests | A turn answered in one short reply with no tool calls, whose output tokens exceed the reply by 3k+ |
| 19 | **Compaction cost** | Retries, automation, and context rebuilding | Writing the summary, then re-reading everything after it | Summary size plus cache rewrites right after each compaction (the summary call's input isn't in transcripts) |
| 20 | **Correction churn** | Retries, automation, and context rebuilding | You keep steering with "no", "that's wrong", "revert", "not like that" | Work done in turns whose prompt matches the hook's correction pattern |
| 21 | **Visual iteration loops** | Images, PDFs, and browser interaction | Edit → screenshot → tweak → screenshot cycles in Figma-to-code or simulator work | Edit-then-screenshot cycles in one task beyond 3 |
| 22 | **Re-learning the codebase** | Repository discovery and file reading | Every session in a project starts by reading the same files, because what was learned was never saved | Files read before the first edit that 2+ earlier sessions of the project also explored |

---

## Still proposed

Not in the report yet.

| Category | What it catches | Detection signal |
|---|---|---|
| **Memory/CLAUDE.md bloat** | Large instruction files loaded every session | Size of injected `CLAUDE.md` and memory content |
| **Wrong working directory** | Sessions started from `~` instead of the project, so searches run across the whole home dir | Session cwd = home dir combined with broad `find`/`grep` |
| **Whole-file reads** | Reading a full file when only a slice was needed | `Read` with no offset/limit on files over ~500 lines |
| **Generated/vendor files** | Reading lockfiles, `.pbxproj`, minified JS, build output | Path matches |
| **Large pastes** | Logs or code pasted straight into the prompt | User message token size |
| **Full-page dumps** | `read_page` or `get_page_text` when a targeted `find` would do | Tool name plus result size |
| **Figma over-fetching** | `get_design_context` on large parent frames instead of child nodes | Node size and repeated calls on the same file |
| **Abandoned sessions** | Spend that ends with no edits, commits, or deploys | Sessions with zero write actions |
| **Polling** | Repeatedly checking deploy, build, or CI status | Same read-only tool called N times in a row |

The canvas lists about 110 more categories under the same 14 headings; see its "Additional categories" section.

---

## Open questions

- **#6 Bigger model than needed**: no good measure yet of the real problem (people on higher plans never switch to a cheaper model). The report now shows the share of main-session spend on Opus/Fable as a first signal.
- **#12 and #13** need the list of loaded tools and skills, which transcripts don't contain.

---

## Where to start

1. **MCP schema bloat** and **wrong working directory**: probably a large part of the $413 "Heavy starting context" row. Disconnecting rarely used MCP servers could cut every call.
2. **Screenshot accumulation** and **Figma over-fetching**: the mobile/Figma sessions (BIT-landers-nsf-mobile) appear at the top of several leak rows.
3. **Fork context duplication**: multiplies the starting-context problem inside the $172 "Many agents" row.
4. **Enable hooks (#11)**: unlocks idle detection and per-session categorization.
