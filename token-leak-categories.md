# Token Leak Categories

Reference for the `token-metrics:leak-report` categories: what each one catches, how it is detected, and ideas not built yet.

By default the report shows **43 categories** in 11 groups, numbered 1-50 (seven numbers are retired and never reused, see below). They are built from the team's [Leak Categories canvas](https://devxconsultancy.slack.com/docs/T046R1BS75M/F0C61Q25V5J): each one sums one or more canvas detectors (the "Canvas rows" column). Rows that cost nothing in practice, measured the same thing twice, or can't be measured from transcripts were folded in or dropped; the full canvas list is still printed with `--all` and documented further down. The list lives in `plugins/token-metrics/scripts/leak_categories.py`.

When a category merges several detectors and two of them flag the same tool result (for example one `git diff` that is both large and full of lockfile changes), that result counts once, at the larger cost.

Thresholds are defaults that can be changed in a config file, and five categories (8, 10, 12, 22, 26) use a model to label prompts or turns. Both are described under "Config file" and "Prompt check" below.

---

## The 43 categories

Numbers were assigned by cost for 2026-09-01 to 2026-10-01 and stay fixed; the report still sorts by cost on every run. "Review" means spend to look at, not all waste. Review rows (17, 18, 26, 29, 47) are printed in a separate "Spend to review" table after the leaks and are not counted in the waste index. "Part of" rows (48, 49) price part of another row's tokens: they are shown next to it and not counted again.

| # | Leak | Group | What it catches | Canvas rows |
|---|---|---|---|---|
| 1 | **Heavy starting context** | Starting context and setup | Sessions whose first call carries more than 60k tokens (system prompt, tools, memory, CLAUDE.md), repeated on every call. The note breaks the starting context into built-in tools, skill and agent listings, CLAUDE.md and memory, and MCP instructions, from the recorded attachments | #1 |
| 4 | **Cache expired after a break** | Prompt cache | A break longer than the cache lifetime of that write (5m or 1h, as recorded), so the context is rewritten. Small rewrites (under 10k tokens) are not flagged | #3a |
| 5 | **Many agents** | Agents | Agent spawns that cost more than doing the work in the main thread: few tool calls, or a startup many times larger than what the agent read | #4 |
| 6 | **Long history replay** | Conversation history | A long-running session whose average context is above 60% of the model's window. The note shows what the context was made of at its peak (tool results, screenshots, starting context, replies, prompts) | A1 |
| 7 | **Interrupted turns** | Retries and rework | Turns stopped before they finished, whose work is then redone | A134 |
| 8 | **Sessions that never end** | Conversation history | A prompt that starts an unrelated task in a session carrying a large history. Flagged only for sessions with 2 or more such switches carrying 50k+ tokens | #2 |
| 9 | **No clear direction** | Exploration and file reading | Reads and searches before the first edit whose results were never used again (dead ends) | #5 |
| 10 | **Restarting too often** | Conversation history | A new session that could have continued a recent one and re-read its files before its first edit | A10 |
| 12 | **Bigger model than needed** | Model and output | Opus/Fable or Sonnet turns that a model judge (see Prompt check) says the next model down would have done equally well, priced against that model. Turns not judged yet use a size heuristic (short prompt, small output, few tool calls, tiny edits, little thinking) | #6 |
| 13 | **Fork context duplication** | Agents | Helper agents that start with most of the parent's context (80%+, and well above a fresh start) | #4a (= A121) |
| 16 | **Model switch rewrote the cache** | Prompt cache | Switching models, so the new model writes the context from scratch | A30 |
| 17 | **Old replies replayed** (review) | Conversation history | Earlier assistant text re-read on every later call | A6 |
| 18 | **Clarification loops** (review) | Retries and rework | Turns spent asking clarifying questions | A131 |
| 20 | **Visual iteration loops** | Images and browser | Edit -> screenshot cycles that made no visible progress: the same screenshot again, or an edit that undid an earlier one | #21 |
| 21 | **Cache not reused** | Prompt cache | Cache writes never read back, uncached calls, prefixes too short to cache | A35, A21, A24 |
| 22 | **Correction churn** | Retries and rework | Work redone after a prompt that rejects the previous answer (only the redone edits are charged) | #20 |
| 23 | **Agents racing the cache** | Prompt cache | Helper agents writing the same cache at the same moment | A34 |
| 24 | **Too much tool output** | Tool and terminal output | Non-shell tool results above 4k tokens, the part above 2k charged (re-reads and dependency hits are in 43 and 41) | #7 |
| 25 | **Noisy and repeated terminal output** | Tool and terminal output | Repeated log lines, repeated tracebacks and lint output, and commands rerun with the same output. Size alone no longer counts | A87, A82, A84, #17a |
| 26 | **Repeated tasks across sessions** (review) | Conversation history | A request repeated from an earlier session that again edits 50%+ of the same files | #15 |
| 27 | **Failed, retried and polling calls** | Retries and rework | Tool-marked errors, the same failing call repeated, the same call returning the same result | #16, #9, A136 (A135 is part of #16) |
| 28 | **Repeated screenshots** | Images and browser | Back-to-back screenshots, unchanged screenshots, screenshots retaken after a failed browser action | A114, A112, A120 |
| 29 | **Progress narration** (review) | Model and output | More than 50 tokens of text around each tool call | A54 |
| 30 | **Whole-file reads** | Exploration and file reading | Unsliced reads of files above 5k tokens | A71 |
| 32 | **Agent coordination chatter** | Agents | Messages sent between agents | A126 |
| 33 | **Large images and PDFs** | Images and browser | Oversized images and PDFs read into context, and documents read both as page images and as extracted text | A111, A115, A116, A117 |
| 34 | **Broad or unbounded searches** | Exploration and file reading | Searches returning 100+ lines or with no path/type limit | A73, A79 |
| 35 | **Bloated JSON and query results** | Tool and terminal output | Large JSON and database results, results that are mostly keys and wrappers | A98, A99, A100 |
| 36 | **Wordy and repeated output** | Model and output | Whole-file rewrites where the recorded patch changed 30% or less of the file, restating the request, repeated explanations or code, truncated replies | #8, A52, A53, A58, A60 |
| 37 | **Web pages and search results** | Web research | Full pages, attached documents, too many search results, repeated fetches and passages, different sources with the same content | A101, A109, A103, A105, A107, A110, A104 |
| 38 | **Copied history (pastes, transcripts, forks)** | Conversation history | Background pasted again, chat transcripts pasted in, forked conversations | A7, A8, A9 |
| 39 | **Compaction cost** | Conversation history | Writing the summary and re-reading after it, for automatic compactions only (a manual `/compact` between tasks is the cure) | #19 |
| 40 | **Git and GitHub output** | Tool and terminal output | Large diffs, lockfile diffs, verbose logs, repeated status, PR and issue histories | A91-A96 |
| 41 | **Dependency, vendor and generated files** | Exploration and file reading | Reads and search hits in `node_modules`, build output, lockfiles and generated code | A76, A77 |
| 42 | **Verbose agent reports** | Agents | Agent reports that are long relative to what the agent read (briefs are no longer in this row) | #4c (= A127) |
| 43 | **Repeated reads of unchanged files** | Exploration and file reading | The same file read again without an edit in between | A72 |
| 44 | **Re-learning the codebase** | Exploration and file reading | Files that 3+ sessions in the last 30 days also explored before their first edit. The note compares sessions with and without a CLAUDE.md | #22 |
| 45 | **High effort on trivial turns** | Model and output | Long recorded thinking behind a short reply with no tool calls | #18 |
| 46 | **Tool discovery and skill loading** | Starting context and setup | Repeated tool-search calls, reads of skill supporting documents, and invoked skill bodies above 3k tokens | A65, A69, A68 |
| 47 | **Usage while idle** (review) | Retries and rework | Turns not started by a person, by each prompt's recorded origin (hook data if the version doesn't record it). Information, since a `/loop` may be intended | #10 |
| 48 | **MCP tool schema bloat** (part of 1) | Starting context and setup | Definitions of MCP servers that were loaded but called in fewer than 20% of the sessions that loaded them | #12 |
| 49 | **Unused skills/plugins** (part of 1) | Starting context and setup | Listed skills that were not invoked in any session within 14 days either side | #13 |
| 50 | **No visibility** | Observability | Sessions without hook data, so categories, ratings and idle time are unknown | #11 |

### Retired

These numbers are never reused. The tokens are still counted, in the row named here.

| # | Retired category | Where it is counted now |
|---|---|---|
| 2 | Cache-write premium | Nowhere: it is the normal price of caching. Rewrites after a break are in 4 |
| 3 | Cold cache at session and agent start | Nowhere as a leak: every session writes its context once. The size of that context is in 1, agent starts are in 5 |
| 11 | Stale tool results carried forward | Part of 6's context breakdown |
| 14 | Large tool-call arguments | Dropped: it was almost all real work (scripts, plans) |
| 15 | Agent startup cost | The cost side of 5's low-value spawn check |
| 19 | Screenshot accumulation | Part of 6's context breakdown |
| 31 | Duplicate reading across agents | Dropped: both cases (sibling read, parent re-read) have legitimate reasons. Still printed with `--all` as #4b and A128 |

Only shown with `--all`: A45 (replanning, never triggered), user denials of tool calls (A135 and the denied part of #16 are kept there), the instruction, prompt-cache and other canvas rows that would double count a curated row (for example A17 inside 1, A27 inside 4), and the 29 canvas rows that can't be measured from transcripts.

---

## Prompt check

Categories 8, 10, 22 and 26 and the task boundaries depend on what a prompt means: is it an unrelated task, a correction, a continuation of an earlier session, a repeat of an earlier request? Keywords get this wrong, so `prompt_check.py` asks a model. Category 12 uses the same check as a model judge: for each Opus/Fable or Sonnet turn it sees the prompt, the previous prompt, what the turn did (tools used, lines edited, output and reasoning tokens) and the start of the reply, and decides whether the next model down would have done it equally well.

- It runs `claude -p` with Sonnet, using the person's own Claude Code login. Prompt text (the first 500 characters of each typed prompt, short excerpts of earlier sessions of the same project, and for the judge the first 300 characters of each turn's final reply) is sent to the model, nothing else. Nothing goes to the leaderboard.
- It is on by default. Turn it off with `"prompt_check": false` in the config file or `CC_METRICS_PROMPT_CHECK=0` in the environment. The report then falls back to keywords and file overlap: a correction pattern that doesn't count at the start of a task (22), idle gap plus a prompt naming no earlier file (8), the previous session within 24 hours (10), word overlap (26).
- Labels are cached in `prompt_checks.json` in the metrics directory, keyed by a hash of the prompt. No prompt text is stored, so a re-run costs nothing for prompts already labelled. At most 60 new model calls are made per run (`prompt_check_max_calls`); the rest are labelled on the next run.
- The report header says how many multi-prompt sessions were labelled. Any failure leaves the labels unknown and the fallbacks apply; the check never stops a report.

## Config file

Thresholds live in `plugins/token-metrics/scripts/leak_config.py`. To change one, put the key in `config.json` in the metrics directory (`~/.claude/metrics`, or `$CC_METRICS_DIR`), for example `{"start_context_threshold": 80000, "prompt_check": false}`. Unknown keys are ignored and a broken file falls back to the defaults.

| Category | Keys (default) |
|---|---|
| 1 | `start_context_threshold` (60,000 tokens) |
| 4 | `break_rewrite_min` (10,000) |
| 5 | `agent_min_tools` (3), `agent_startup_ratio` (5) |
| 6 | `long_context_share` (0.6), `long_session_min_calls` (50), `history_keep` (100,000), `context_window` (inferred: where Claude Code auto-compacted, else 1M or 200k) |
| 8 | `carry_min` (50,000), `unrelated_switch_min` (2) |
| 9 | `dead_end_min` (5) |
| 10 | `restart_window_h` (24) |
| 12 | `small_prompt_tokens` (150), `small_output_tokens` (1,500), `small_tool_calls` (3), `small_edit_lines` (10), `small_thinking_tokens` (1,000) |
| 13 | `fork_share` (0.8) |
| 24 | `big_result` (4,000), `big_keep` (2,000) |
| 26 | `repeat_edit_overlap` (0.5) |
| 36 | `rewrite_changed_share` (0.3) |
| 42 | `report_big` (2,500), `report_keep` (1,000), `report_work_ratio` (0.5) |
| 44 | `relearn_min_sessions` (3), `relearn_days` (30) |
| 45 | `think_limit` (3,000), `think_ratio` (5) |
| 48 | `rare_server_share` (0.2) |
| 49 | `unused_skill_days` (14) |
| Prompt check | `prompt_check` (true), `prompt_check_model` ("sonnet"), `prompt_check_max_calls` (60), `prompt_check_workers` (4), `prompt_check_timeout_s` (120) |

---

## Current report snapshot (2026-10-12 to 2026-11-21)

119 sessions, API-equivalent spend **$641.96**, prompt check on (87 of 87 multi-prompt sessions labelled). Top 15 of the 43:

| # | Leak | Est. cost | Share of spend |
|---|---|---|---|
| 4 | Cache expired after a break | $51.81 | 8.1% |
| 12 | Bigger model than needed | $32.60 | 5.1% |
| 8 | Sessions that never end | $27.73 | 4.3% |
| 7 | Interrupted turns | $25.21 | 3.9% |
| 6 | Long history replay | $21.42 | 3.3% |
| 9 | No clear direction | $14.89 | 2.3% |
| 39 | Compaction cost | $8.88 | 1.4% |
| 24 | Too much tool output | $8.02 | 1.2% |
| 1 | Heavy starting context | $6.29 | 1.0% |
| 21 | Cache not reused | $4.57 | 0.7% |
| 35 | Bloated JSON and query results | $4.14 | 0.6% |
| 49 | Unused skills/plugins (part of 1) | $3.81 | 0.6% |
| 23 | Agents racing the cache | $3.33 | 0.5% |
| 5 | Many agents | $3.19 | 0.5% |
| 28 | Repeated screenshots | $3.14 | 0.5% |

Spend to review: 47 Usage while idle $33.68 (5.2%, mostly turns started by task notifications), 17 Old replies replayed $5.82, 18 Clarification loops $2.35, 29 Progress narration $0.71, 26 Repeated tasks across sessions $0.00.

Two things changed against the earlier snapshot. The old top rows (heavy starting context, cache-write premium, cold cache, MCP schema bloat) are much smaller or gone: 1 now charges only the part of the starting context above 60k, 2 and 3 are retired, and 48 only counts servers called in under 20% of the sessions that loaded them. And 1's note shows what the starting context is made of: built-in tools 56%, skill and agent listings 15%, CLAUDE.md and memory 9%, MCP instructions and deferred tool names 8%; the median start is about 56k tokens and 35% of sessions start above 60k.

Costs overlap, so they don't add up to the total.

---

## Full canvas list (`--all`)

`--all` prints the canvas numbering instead: 1-11 are the core leaks, 12-22 the additional ones, 4a-4c break down #4, 3a breaks out the break-only part of #3, and 17a is the unchanged-rerun part of #17, and the A rows follow in a second table (`--all --core` hides it). The tables below give the detection signal for each canvas row.

### Core rows
| # | Leak | Category | What it catches | Detection signal |
|---|---|---|---|---|
| 1 | **Heavy starting context** | Persistent instructions and memory | Sessions whose very first call already carries a large prompt: system prompt, tool definitions, memory, CLAUDE.md. That cost repeats on every call. | First-request context above 60k tokens (`start_context_threshold`), the part above it re-read on every call. The breakdown (built-in tools, skill and agent listings, CLAUDE.md and memory, MCP instructions) is read from the recorded attachments |
| 2 | **Sessions that never end** | Conversation history | One session reused for unrelated tasks, so a new task carries all the old context with it | An unrelated new task (prompt check label, else an idle gap plus a prompt naming no file read earlier; a notification never starts a task) carrying 50k+ tokens of history. Flagged only for sessions with 2+ such switches |
| 3 | **Losing the cache** | Cache misses and invalidation | Breaks long enough for the prompt cache to expire, so the next call rewrites the whole context at full write price | Large cache writes after a break, model switch or recorded prefix change (tools, system prompt, effort, organization; also counted in A25-A40), otherwise "context changed" (rewrites after compaction go to #19). Parent of 3a; not a curated row |
| 3a | **Cache expired after a break** | Cache misses and invalidation | The part of #3 caused by a break past the cache lifetime | Rewrites of #3 after a gap longer than the lifetime of that write, read per write from the recorded 5m/1h split (`--ttl` only where an entry has no split); rewrites under 10k tokens (`break_rewrite_min`) are not flagged; not model switches or prefix changes |
| 4 | **Many agents** | Multi-agent workflows | Heavy use of subagents, each with its own context and calls. Not always waste. | Low-value spawns, per agent: fewer than 3 tool calls, or a startup context 5+ times what the agent read. Charged: the agent's cost beyond what the work needed. Replaces the old call count and share of session cost |
| 4a | **Fork context duplication** | Multi-agent workflows | Forked subagents inherit the full parent context, so each one starts at 160k+ | Helper agent whose first call is at least 80% of the parent's context and well above a fresh agent start; excess re-read on each of its calls |
| 4b | **Overlapping agents** | Multi-agent workflows | Parallel agents reading the same files | A file `Read` by a helper agent after a sibling agent already read it. `--all` only |
| 4c | **Verbose agent reports** | Multi-agent workflows | Large subagent results pulled back into the main context | `Agent`/`Task` result above 2.5k tokens that is long relative to what the agent read (a long report from a long investigation is not flagged) |
| 5 | **No clear direction** | Repository discovery and file reading | Long exploration before any change is made, usually because the task or target files weren't clear up front | Reads and searches before a task's first edit whose results were never used again: the file is not named in a later reply or tool input, or a search found no file that was later opened. Flagged at 5+ dead ends in a task |
| 6 | **Bigger model than needed** | Model selection and reasoning | Opus used where Sonnet or Haiku would do, mostly helper agents doing searches or simple tasks | Opus/Fable or Sonnet turns the model judge says the next model down would have done equally well (routine work: lookups, commands, small mechanical edits, docs from existing context; not debugging, design or subtle correctness), priced against that model. Unjudged turns fall back to a size heuristic. The old tag rule and helper-agent rule are gone; the note shows the share of turns flagged and how many were judged |
| 7 | **Too much tool output** | Tools, MCP, skills, and plugins | Single tool results large enough to bloat context for the rest of the session | Duplicate reads, dependency-folder hits, non-shell results above 4k tokens (the part above 2k charged; thresholds in config) |
| 8 | **Wordy responses** | Answer and artifact generation | Output tokens spent on long replies or on rewriting whole files where an edit would do | A `Write` over an existing file whose recorded patch changed 30% or less of it (an `Edit` would have written only that part); output share of spend |
| 9 | **Retry loops** | Retries, automation, and context rebuilding | The same failing action repeated with little or no change | The same tool input failing 3+ times. A shell non-zero exit counts only as a retry, not as an error; an edit in between resets the count (the rerun tests the fix) |
| 10 | **Usage while idle** | Retries, automation, and context rebuilding | Tokens spent while no one is at the keyboard: background loops, monitors, scheduled wakeups | Turns not started by a person, by each prompt's recorded origin; older sessions fall back to hook data (prompts with no hook record within 15 s, only after the session's first hook record). Information: a `/loop` or scheduled task may be intended |
| 11 | **No visibility** | Observability coverage | Sessions with no hook data, so the report can't categorize them, collect ratings, or detect idle time | Share of sessions with hook data |
| 12 | **MCP tool schema bloat** | Tools, MCP, skills, and plugins | Connected servers whose tool definitions get sent on every call | Tool definitions from the transcript's prompt snapshots, judged across sessions: servers loaded with full definitions (deferred tools excluded) but called in under 20% of the sessions that loaded them. Charged in the sessions that loaded and didn't call them. Shown as part of #1, not counted in the waste index. Sessions without snapshots are skipped |
| 13 | **Unused skills/plugins** | Tools, MCP, skills, and plugins | Skill and plugin listings injected but never invoked | The skill listing and agent listing attachments: skills not invoked (Skill tool or slash command) in any session within 14 days either side. Shown as part of #1, not counted in the waste index |
| 14 | **Screenshot accumulation** | Images, PDFs, and browser interaction | Every screenshot (Figma, Chrome, simulator) stays in context for the rest of the session | Image blocks in tool results, sized from their pixels, re-read after first use until compaction. Retired as a curated row; now part of #6's context breakdown |
| 15 | **Repeated tasks across sessions** | Conversation history | The same request redone in several sessions | The prompt check says the first request repeats an earlier session's (else 60%+ word overlap) and 50%+ of the same files are edited again; spend to review |
| 16 | **Failed/denied tool calls** | Retries, automation, and context rebuilding | Schema errors, permission denials, wrong IDs (common with MCP tools) | Tool-marked `is_error` results, classified as schema error / wrong id; error text carried plus the wasted call's output. User denials are excluded (kept for `--all`); shell non-zero exits are ordinary results |
| 17 | **Noisy commands** | Terminal, build, and test output | Build or install output dumped in full (`xcodebuild`, `npm install`, `pod install`) | Repeated log lines, tracebacks and lint output (A87, A82, A84) and 17a. Size alone no longer counts; `Bash` results above 4k tokens are still listed under `--all` |
| 18 | **High effort on trivial turns** | Model selection and reasoning | Long thinking on simple requests | A turn answered in one short reply with no tool calls, whose recorded thinking tokens exceed 3k and 5 times the reply |
| 19 | **Compaction cost** | Retries, automation, and context rebuilding | Writing the summary, then re-reading everything after it | Summary size plus cache rewrites right after each automatic compaction (the summary call's input isn't in transcripts). A manual `/compact` isn't counted |
| 20 | **Correction churn** | Retries, automation, and context rebuilding | You keep steering with "no", "that's wrong", "revert", "not like that" | A prompt that rejects the previous answer (prompt check label, else the keyword pattern on a prompt that doesn't start a task). Only redone work is charged: edits to a file the previous turn edited, or reverts |
| 21 | **Visual iteration loops** | Images, PDFs, and browser interaction | Edit → screenshot → tweak → screenshot cycles in Figma-to-code or simulator work | Edit-then-screenshot cycles with no progress: the screenshot is identical (by hash) to the previous cycle's, or the cycle's edit reverted an earlier edit |
| 22 | **Re-learning the codebase** | Repository discovery and file reading | Every session in a project starts by reading the same files, because what was learned was never saved | Files read before the first edit that 3+ sessions of the project in the last 30 days also explored. The note compares sessions with and without a CLAUDE.md |
| 17a | **Unchanged command reruns** | Terminal, build, and test output | The same `Bash` command run again with the same output | Second run of a command whose output hash is unchanged. Part of #17; counted in curated #25 |

---

### Still proposed

Not in the report yet.

| Category | What it catches | Detection signal |
|---|---|---|
| **Wrong working directory** | Sessions started from `~` instead of the project, so searches run across the whole home dir | Session cwd = home dir combined with broad `find`/`grep` |
| **Large pastes** | Logs or code pasted straight into the prompt | User message token size |
| **Figma over-fetching** | `get_design_context` on large parent frames instead of child nodes | Node size and repeated calls on the same file |
| **Abandoned sessions** | Spend that ends with no edits, commits, or deploys | Sessions with zero write actions |


---

### Additional categories (A rows)

The canvas's "Additional categories" section, in the report's second table as A<canvas row>. 77 are measured from transcripts, 3 share a core row's measure, and 29 are unmeasurable and shown with the reason instead of $0.00. Detection logic is in `plugins/token-metrics/scripts/leak_extra.py`; A25-A27, A29, A30, A38, A40, A72, A76 and A135 are recorded by the core detectors in `leak_report.py`.

Besides messages and tool results, newer Claude Code transcripts record `attachment` entries: the loaded CLAUDE.md and memory files (`instructions`), skill and agent listings, MCP server instructions, and `prompt_snapshot`s with the system prompt and every tool definition. The instruction, listing and snapshot rows below read those. Invoked skill bodies are recorded as meta messages linked to their Skill call.

| # | Leak | Category | Status |
|---|---|---|---|
| A1 | Long single-thread history replay | Conversation history | Measured: a session of 50+ calls whose average context is above 60% of the window; the history above 100k charged on every call, with a breakdown of the peak context |
| A3 | Obsolete requirements retained in context | Conversation history | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A4 | Abandoned approaches retained in context | Conversation history | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A5 | Old tool results carried into later turns | Conversation history | Measured |
| A6 | Previous assistant answers repeatedly replayed | Conversation history | Measured (spend to review) |
| A7 | Repeatedly pasted background information | Conversation history | Measured |
| A8 | Full transcripts copied between chats | Conversation history | Measured |
| A9 | Conversation forks duplicating history | Conversation history | Measured |
| A10 | Rebuilding context after frequent fresh starts | Conversation history | Measured: a session that could have continued a recent one (prompt check match, else the previous session within 24 hours, unless that one was already too long) and re-read its files before the first edit |
| A14 | Overlapping directory-level instructions | Persistent instructions and memory | Measured: lines (30+ chars) repeated between two loaded project `CLAUDE.md` files at different directory levels |
| A16 | Duplicate rules across instruction layers | Persistent instructions and memory | Measured: lines repeated between instruction layers (project, local, user, memory) |
| A17 | Irrelevant always-loaded project guidance | Persistent instructions and memory | Measured (spend to review): always-loaded project and local guidance above 2k tokens |
| A18 | Stale auto-memory entries | Persistent instructions and memory | Measured: memory index lines linking to memory files that no longer exist (checked when the report runs) |
| A19 | Excessive few-shot examples | Persistent instructions and memory | Measured: `<example>` blocks beyond 2 per tool description, system prompt or instruction file |
| A20 | Conflicting instructions causing corrective turns | Persistent instructions and memory | Unmeasurable: needs a labelled review of what was relevant or necessary (all corrections are counted in #20) |
| A21 | Missing prompt caching where supported | Cache misses and invalidation | Measured |
| A22 | Cold-cache requests | Cache misses and invalidation | Measured (spend to review) |
| A24 | Prefixes below cache eligibility thresholds | Cache misses and invalidation | Measured |
| A25 | Timestamps inside otherwise stable prefixes | Cache misses and invalidation | Measured: a cache rewrite after the system prompt changed only in its digits (a timestamp); part of #3 |
| A26 | Changing system-prompt content | Cache misses and invalidation | Measured: a cache rewrite after the recorded system prompt changed; part of #3 |
| A27 | Changing loaded tool definitions | Cache misses and invalidation | Measured: a cache rewrite after the recorded tool definitions changed; part of #3 |
| A28 | Editing earlier conversation messages | Cache misses and invalidation | Unmeasurable: needs the exact request body (cache_control breakpoints, edited messages), which transcripts don't record |
| A29 | Unstable tool serialization or ordering | Cache misses and invalidation | Measured: a cache rewrite after the same tool definitions were sent in a different order; part of #3 |
| A30 | Switching models with no reusable cache on the receiving model | Cache misses and invalidation | Measured |
| A31 | Cache breakpoints on changing content | Cache overhead and configuration | Unmeasurable: needs the exact request body (cache_control breakpoints, edited messages), which transcripts don't record |
| A32 | Stable content outside cached prefixes | Cache overhead and configuration | Unmeasurable: needs the exact request body (cache_control breakpoints, edited messages), which transcripts don't record |
| A33 | Cache breakpoint lookback limits | Cache overhead and configuration | Unmeasurable: needs the exact request body (cache_control breakpoints, edited messages), which transcripts don't record |
| A34 | Concurrent requests before cache creation completes | Cache overhead and configuration | Measured |
| A35 | Cache writes never reused | Cache overhead and configuration | Measured |
| A36 | Repeated cache warmup requests | Cache overhead and configuration | Unmeasurable: these model calls are not recorded in transcripts |
| A37 | Cache-write pricing premiums | Cache overhead and configuration | Measured (spend to review) |
| A38 | Thinking or effort changes invalidating cached context | Cache overhead and configuration | Measured: a cache rewrite right after `/effort`; part of #3 |
| A39 | Tool-choice or web-tool configuration changes | Cache overhead and configuration | Unmeasurable: depends on settings or provider scope that transcripts don't record (tool_choice; web tools added or removed are counted in A27) |
| A40 | Cache isolation across providers or workspaces | Cache overhead and configuration | Measured: a cache rewrite after the session switched organization (workspace); provider switches aren't recorded; part of #3 |
| A42 | Excessive extended-thinking generation | Model selection and reasoning | Unmeasurable: needs matched runs with independent acceptance checks |
| A43 | Replayed thinking blocks where preserved | Model selection and reasoning | Unmeasurable: transcripts record thinking blocks, but not whether later requests kept them (depends on the model) |
| A44 | Repeated reasoning over unchanged evidence | Model selection and reasoning | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A45 | Replanning after every minor update | Model selection and reasoning | Measured |
| A46 | Generating unnecessary alternative approaches | Model selection and reasoning | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A47 | Repeated self-critique cycles | Model selection and reasoning | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A48 | Model handoffs requiring context reconstruction | Model selection and reasoning | Unmeasurable: needs a labelled review of what was relevant or necessary (the cache rewrite is counted in A30) |
| A49 | Switching models followed by duplicate task execution | Model selection and reasoning | Unmeasurable: needs matched runs with independent acceptance checks |
| A50 | Tokenizer differences between model versions | Model selection and reasoning | Unmeasurable: needs the same payload counted on both models |
| A52 | Repeating the user's question | Answer and artifact generation | Measured |
| A53 | Repeating already-established explanations | Answer and artifact generation | Measured |
| A54 | Unnecessary progress narration | Answer and artifact generation | Measured (spend to review) |
| A55 | Excessive examples | Answer and artifact generation | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A56 | Multiple unsolicited solution variants | Answer and artifact generation | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A58 | Reprinting previously generated artifacts | Answer and artifact generation | Measured |
| A59 | Duplicating information across output formats | Answer and artifact generation | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A60 | Truncated answers requiring regeneration | Answer and artifact generation | Measured |
| A65 | Unnecessary tool discovery calls | Tools, MCP, skills, and plugins | Measured |
| A66 | Large tool-call argument payloads | Tools, MCP, skills, and plugins | Measured |
| A68 | Large invoked skill bodies | Tools, MCP, skills, and plugins | Measured: invoked skill bodies above 3k tokens, beyond 1.5k charged until compaction |
| A69 | Unnecessary skill supporting-document reads | Tools, MCP, skills, and plugins | Measured (spend to review) |
| A70 | Verbose plugin or hook context injection | Tools, MCP, skills, and plugins | Measured: MCP server instructions and hook-injected context above 300 tokens per block |
| A71 | Whole-file reads for small relevant sections | Repository discovery and file reading | Measured |
| A72 | Repeated reads of unchanged files | Repository discovery and file reading | Measured |
| A73 | Broad repository searches | Repository discovery and file reading | Measured |
| A76 | Reading dependency or vendor source | Repository discovery and file reading | Measured |
| A77 | Reading generated files | Repository discovery and file reading | Measured |
| A79 | Searching without useful path or symbol boundaries | Repository discovery and file reading | Measured |
| A82 | Repeated failure tracebacks | Terminal, build, and test output | Measured |
| A84 | Repeated linter diagnostics | Terminal, build, and test output | Measured |
| A87 | Repeated runtime log lines | Terminal, build, and test output | Measured |
| A91 | Large Git diffs with irrelevant context | Git, collaboration, and structured data | Measured |
| A92 | Generated-file or lockfile diffs | Git, collaboration, and structured data | Measured |
| A93 | Verbose commit-history metadata | Git, collaboration, and structured data | Measured |
| A94 | Repeated working-tree status dumps | Git, collaboration, and structured data | Measured |
| A95 | Full pull-request discussions | Git, collaboration, and structured data | Measured |
| A96 | Full issue-tracker histories | Git, collaboration, and structured data | Measured |
| A98 | Large JSON responses with unused fields | Git, collaboration, and structured data | Measured |
| A99 | Database results with unnecessary rows or columns | Git, collaboration, and structured data | Measured |
| A100 | Repetitive metadata and serialization wrappers | Git, collaboration, and structured data | Measured |
| A101 | Full web pages instead of relevant passages | Web research and retrieval | Measured |
| A102 | Navigation, footer, and website boilerplate | Web research and retrieval | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A103 | Excessive search-result counts | Web research and retrieval | Measured |
| A104 | Duplicate sources containing the same information | Web research and retrieval | Measured: a web page or search result 50%+ the same (8-word shingles) as an earlier result from another URL or query |
| A105 | Repeated fetching of unchanged pages | Web research and retrieval | Measured |
| A107 | Overlapping retrieval chunks | Web research and retrieval | Measured |
| A108 | Irrelevant retrieved passages | Web research and retrieval | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A109 | Entire documents attached for narrow questions | Web research and retrieval | Measured (spend to review) |
| A110 | Repeated retrieval after losing source references | Web research and retrieval | Measured |
| A111 | Large image payloads | Images, PDFs, and browser interaction | Measured |
| A112 | Repeated unchanged screenshots | Images, PDFs, and browser interaction | Measured |
| A113 | Full-screen screenshots for small relevant regions | Images, PDFs, and browser interaction | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A114 | Excessive screenshots during browser navigation | Images, PDFs, and browser interaction | Measured |
| A115 | Multi-page PDF processing | Images, PDFs, and browser interaction | Measured (spend to review) |
| A116 | PDF page-image processing alongside extracted text | Images, PDFs, and browser interaction | Measured: the same PDF read as page images and through a text extractor (`pdftotext`, `pypdf`, ...); the later read is charged |
| A117 | Duplicate OCR and document-text inputs | Images, PDFs, and browser interaction | Measured: the same document read as images and through OCR (`tesseract`, `ocrmypdf`, ...) |
| A119 | Large image batches containing irrelevant images | Images, PDFs, and browser interaction | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A120 | Browser retries repeatedly loading the same visual context | Images, PDFs, and browser interaction | Measured |
| A121 | Full context copied to every agent | Multi-agent workflows | Same measure as #4a |
| A122 | Duplicate investigations across agents | Multi-agent workflows | Same measure as #4b |
| A124 | Verbose agent task briefs | Multi-agent workflows | Measured |
| A125 | Repeated agent startup instructions | Multi-agent workflows | Measured (spend to review) |
| A126 | Agent-to-agent coordination chatter | Multi-agent workflows | Measured |
| A127 | Oversized agent result reports | Multi-agent workflows | Same measure as #4c |
| A128 | Parent agents rereading material already reviewed by workers | Multi-agent workflows | Measured |
| A129 | Repeated review and revision rounds | Multi-agent workflows | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A130 | Agents continuing after their work is complete | Multi-agent workflows | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A131 | Ambiguous prompts causing clarification loops | Retries, automation, and context rebuilding | Measured (spend to review) |
| A132 | Missing acceptance criteria causing rework | Retries, automation, and context rebuilding | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A134 | Regeneration after partially completed responses | Retries, automation, and context rebuilding | Measured |
| A135 | Invalid structured outputs requiring repair | Retries, automation, and context rebuilding | Measured |
| A136 | Repeated unchanged-state polling | Retries, automation, and context rebuilding | Measured |
| A137 | Model-powered hooks firing excessively | Retries, automation, and context rebuilding | Unmeasurable: these model calls are not recorded in transcripts |
| A138 | Scheduled tasks repeating unchanged analysis | Retries, automation, and context rebuilding | Measured: a session whose first request matches an earlier one exactly and whose tool results are 80%+ unchanged |
| A140 | Background session-analysis model calls | Retries, automation, and context rebuilding | Unmeasurable: these model calls are not recorded in transcripts |

---

## Open questions

- **12 Bigger model than needed**: the model judge decides with hindsight (it sees what the turn did), and the saving is priced as if the turn had run on the smaller model from the start. Switching mid-session would also rewrite the cache (#16), so the real saving needs the switch at the start of a task.
- **48 and 49** only cover sessions from Claude Code versions that record prompt snapshots and skill listings; older sessions are skipped. They are judged across sessions, so they need several sessions to say anything.
- **8, 10, 22, 26** are only as good as the prompt check. With it off, the keyword fallbacks over-count corrections and miss repeats that are worded differently.

---

## Where to start

1. **Cache expired after a break (4)**: the biggest row in the latest snapshot ($52 of $642). Sessions resumed after hours or days pay to rewrite the whole context; `/clear` or a fresh session before a long break is cheaper than resuming a large one.
2. **Long history replay (6) and Sessions that never end (8)**: the same few mobile/Figma sessions (BIT-landers-nsf-mobile) carry 200k+ tokens across unrelated tasks. The note on 6 says what the context was made of; `/compact` between tasks removes stale tool results and screenshots.
3. **Heavy starting context (1)**: about 35% of sessions start above 60k tokens. The breakdown shows whether built-in tools, skill and agent listings, CLAUDE.md or MCP instructions are the part to cut. **Wrong working directory** may explain more of it.
4. **Enable hooks (50)**: unlocks idle detection and per-session categorization.
