# Token Leak Categories

Reference for the `token-metrics:leak-report` categories: what each one catches, how it is detected, and ideas not built yet.

By default the report shows **50 categories** in 11 groups, numbered 1-50. They are built from the team's [Leak Categories canvas](https://devxconsultancy.slack.com/docs/T046R1BS75M/F0C61Q25V5J): each one sums one or more canvas detectors (the "Canvas rows" column). Rows that cost nothing in practice, measured the same thing twice, or can't be measured from transcripts were folded in or dropped; the full canvas list is still printed with `--all` and documented further down. The list lives in `plugins/token-metrics/scripts/leak_categories.py`.

When a category merges several detectors and two of them flag the same tool result (for example one `git diff` that is both large and full of lockfile changes), that result counts once, at the larger cost.

---

## The 50 categories

Numbers were assigned by cost for 2026-09-01 to 2026-10-01 and stay fixed; the report still sorts by cost on every run. "Review" means spend to look at, not all waste.

| # | Leak | Group | What it catches | Canvas rows |
|---|---|---|---|---|
| 1 | **Heavy starting context** | Starting context and setup | First call already carries a large prompt (system prompt, tools, memory, CLAUDE.md), repeated on every call | #1 |
| 2 | **Cache-write premium** (review) | Prompt cache | The extra paid for cache writes over the normal input price | A37 |
| 3 | **Cold cache at session and agent start** (review) | Prompt cache | The first cache write of each session and helper agent | A22 |
| 4 | **Cache expired after a break** | Prompt cache | A break long enough for the cache to expire, so the whole context is rewritten | #3 |
| 5 | **Many agents** (review) | Agents | Heavy use of subagents, each with its own context and calls | #4 |
| 6 | **Long history replay** (review) | Conversation history | Calls carrying more than 100k tokens of conversation history | A1 |
| 7 | **Interrupted turns** | Retries and rework | Turns stopped before they finished, whose work is then redone | A134 |
| 8 | **Sessions that never end** | Conversation history | A new task in an old session, carrying all the old context | #2 |
| 9 | **No clear direction** | Exploration and file reading | More than 15 reads/searches before the first edit | #5 |
| 10 | **Restarting too often** | Conversation history | A new session soon after the last one, rebuilding the same context | A10 |
| 11 | **Stale tool results carried forward** | Conversation history | Tool results still re-read 30+ calls later | A5 |
| 12 | **Bigger model than needed** | Model and output | Opus/Fable on simple tasks and helper agents | #6 |
| 13 | **Fork context duplication** | Agents | Helper agents that start with the parent's full context | #4a (= A121) |
| 14 | **Large tool-call arguments** | Tool and terminal output | Tool calls with 1k+ tokens of arguments (e.g. long plans) | A66 |
| 15 | **Agent startup cost** (review) | Agents | The startup call of every helper agent | A125 |
| 16 | **Model switch rewrote the cache** | Prompt cache | Switching models, so the new model writes the context from scratch | A30 |
| 17 | **Old replies replayed** (review) | Conversation history | Earlier assistant text re-read on every later call | A6 |
| 18 | **Clarification loops** (review) | Retries and rework | Turns spent asking clarifying questions | A131 |
| 19 | **Screenshot accumulation** | Images and browser | Screenshots that stay in context until compaction | #14 |
| 20 | **Visual iteration loops** | Images and browser | More than 3 edit -> screenshot cycles in one task | #21 |
| 21 | **Cache not reused** | Prompt cache | Cache writes never read back, uncached calls, prefixes too short to cache | A35, A21, A24 |
| 22 | **Correction churn** | Retries and rework | Work done in turns that start with "no", "that's wrong", "revert" | #20 |
| 23 | **Agents racing the cache** | Prompt cache | Helper agents writing the same cache at the same moment | A34 |
| 24 | **Too much tool output** | Tool and terminal output | Non-shell tool results above 4k tokens (re-reads and dependency hits are in 43 and 41) | #7 |
| 25 | **Noisy and repeated terminal output** | Tool and terminal output | Shell output above 4k tokens, repeated log lines, repeated tracebacks and lint output | #17, A87, A82, A84 |
| 26 | **Repeated tasks across sessions** (review) | Conversation history | The same first request in an earlier session of the project | #15 |
| 27 | **Failed, retried and polling calls** | Retries and rework | Errors and denials, the same failing call repeated, the same call returning the same result | #16, #9, A136 (A135 is part of #16) |
| 28 | **Repeated screenshots** | Images and browser | Back-to-back screenshots, unchanged screenshots, screenshots retaken after a failed browser action | A114, A112, A120 |
| 29 | **Progress narration** (review) | Model and output | More than 50 tokens of text around each tool call | A54 |
| 30 | **Whole-file reads** | Exploration and file reading | Unsliced reads of files above 5k tokens | A71 |
| 31 | **Duplicate reading across agents** | Agents | Files read by a sibling agent, or re-read by the parent after a helper read them | #4b (= A122), A128 |
| 32 | **Agent coordination chatter** | Agents | Messages sent between agents | A126 |
| 33 | **Large images and PDFs** | Images and browser | Oversized images and PDFs read into context, and documents read both as page images and as extracted text | A111, A115, A116, A117 |
| 34 | **Broad or unbounded searches** | Exploration and file reading | Searches returning 100+ lines or with no path/type limit | A73, A79 |
| 35 | **Bloated JSON and query results** | Tool and terminal output | Large JSON and database results, results that are mostly keys and wrappers | A98, A99, A100 |
| 36 | **Wordy and repeated output** | Model and output | Whole-file rewrites, restating the request, repeated explanations or code, truncated replies | #8, A52, A53, A58, A60 |
| 37 | **Web pages and search results** | Web research | Full pages, attached documents, too many search results, repeated fetches and passages, different sources with the same content | A101, A109, A103, A105, A107, A110, A104 |
| 38 | **Copied history (pastes, transcripts, forks)** | Conversation history | Background pasted again, chat transcripts pasted in, forked conversations | A7, A8, A9 |
| 39 | **Compaction cost** | Conversation history | Writing the summary and re-reading after it | #19 |
| 40 | **Git and GitHub output** | Tool and terminal output | Large diffs, lockfile diffs, verbose logs, repeated status, PR and issue histories | A91-A96 |
| 41 | **Dependency, vendor and generated files** | Exploration and file reading | Reads and search hits in `node_modules`, build output, lockfiles and generated code | A76, A77 |
| 42 | **Verbose agent reports and briefs** | Agents | Agent results above 2.5k tokens and briefs above 1k | #4c (= A127), A124 |
| 43 | **Repeated reads of unchanged files** | Exploration and file reading | The same file read again without an edit in between | A72 |
| 44 | **Re-learning the codebase** | Exploration and file reading | Files that 2+ earlier sessions also explored before their first edit | #22 |
| 45 | **High effort on trivial turns** | Model and output | Long thinking behind a short reply with no tool calls | #18 |
| 46 | **Tool discovery and skill loading** | Starting context and setup | Repeated tool-search calls, reads of skill supporting documents, and invoked skill bodies above 3k tokens | A65, A69, A68 |
| 47 | **Usage while idle** | Retries and rework | Turns that started without a typed prompt (needs hook data) | #10 |
| 48 | **MCP tool schema bloat** | Starting context and setup | Definitions of MCP tools the session never called, sent on every call (part of 1) | #12 |
| 49 | **Unused skills/plugins** | Starting context and setup | Listed skills and agent types the session never invoked (part of 1) | #13 |
| 50 | **No visibility** | Observability | Sessions without hook data, so categories, ratings and idle time are unknown | #11 |

Only shown with `--all`: A45 (replanning, never triggered), the instruction, prompt-cache and other canvas rows that would double count a curated row (for example A17 inside 1, A27 inside 4), and the 29 canvas rows that can't be measured from transcripts.

---

## Current report snapshot (2026-09-01 to 2026-10-02)

163 sessions, API-equivalent spend **$1,703.41**. Top 15 of the 50:

| # | Leak | Est. cost | Share of spend |
|---|---|---|---|
| 1 | Heavy starting context | $430.19 | 25.3% |
| 2 | Cache-write premium | $338.65 | 19.9% |
| 3 | Cold cache at session and agent start | $254.93 | 15.0% |
| 48 | MCP tool schema bloat | $248.34 | 14.6% |
| 4 | Cache expired after a break | $228.45 | 13.4% |
| 6 | Long history replay | $179.43 | 10.5% |
| 5 | Many agents | $173.72 | 10.2% |
| 7 | Interrupted turns | $160.66 | 9.4% |
| 8 | Sessions that never end | $123.82 | 7.3% |
| 9 | No clear direction | $90.81 | 5.3% |
| 10 | Restarting too often | $87.61 | 5.1% |
| 11 | Stale tool results carried forward | $67.47 | 4.0% |
| 12 | Bigger model than needed | $57.41 | 3.4% |
| 13 | Fork context duplication | $34.58 | 2.0% |
| 14 | Large tool-call arguments | $28.42 | 1.7% |

48 is new since the report started reading the tool definitions Claude Code records. The largest share is the claude.ai Vercel server ($102, 212 tools and ~140k tokens never called), then Gmail, Chrome, Slack and Firebase.

Costs overlap, so they don't add up to the total.

---

## Full canvas list (`--all`)

`--all` prints the canvas numbering instead: 1-11 are the core leaks, 12-22 the additional ones, 4a-4c break down #4, and the A rows follow in a second table (`--all --core` hides it). The tables below give the detection signal for each canvas row.

### Core rows
| # | Leak | Category | What it catches | Detection signal |
|---|---|---|---|---|
| 1 | **Heavy starting context** | Persistent instructions and memory | Sessions whose very first call already carries a large prompt: system prompt, tool definitions, memory, CLAUDE.md. That cost repeats on every call. | First-request context above 10k tokens, re-read on every call |
| 2 | **Sessions that never end** | Conversation history | One session reused for unrelated tasks, so a new task carries all the old context with it | A new task (tag or 30+ min gap) still carrying 20k+ tokens of prior context; compaction count |
| 3 | **Losing the cache** | Cache misses and invalidation | Breaks long enough for the prompt cache to expire, so the next call rewrites the whole context at full write price | Large cache writes after a break, model switch or recorded prefix change (tools, system prompt, effort, organization; also counted in A25-A40), otherwise "context changed" (rewrites after compaction go to #19) |
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
| 12 | **MCP tool schema bloat** | Tools, MCP, skills, and plugins | Connected servers whose tool definitions get sent on every call | Tool definitions from the transcript's prompt snapshots: tokens of each MCP server's tools that the session (or its helpers) never called, re-read on every main call until the tools change. Sessions from Claude Code versions without snapshots are skipped (counted inside #1) |
| 13 | **Unused skills/plugins** | Tools, MCP, skills, and plugins | Skill and plugin listings injected but never invoked | The skill listing and agent listing attachments: entries for skills never invoked (Skill tool or slash command) and agent types never used, carried until compaction (counted inside #1) |
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
| A1 | Long single-thread history replay | Conversation history | Measured (spend to review) |
| A3 | Obsolete requirements retained in context | Conversation history | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A4 | Abandoned approaches retained in context | Conversation history | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A5 | Old tool results carried into later turns | Conversation history | Measured |
| A6 | Previous assistant answers repeatedly replayed | Conversation history | Measured (spend to review) |
| A7 | Repeatedly pasted background information | Conversation history | Measured |
| A8 | Full transcripts copied between chats | Conversation history | Measured |
| A9 | Conversation forks duplicating history | Conversation history | Measured |
| A10 | Rebuilding context after frequent fresh starts | Conversation history | Measured |
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

- **12 Bigger model than needed**: no good measure yet of the real problem (people on higher plans never switch to a cheaper model). The report now shows the share of main-session spend on Opus/Fable as a first signal.
- **48 and 49** only cover sessions from Claude Code versions that record prompt snapshots and skill listings; older sessions are skipped.

---

## Where to start

1. **MCP schema bloat (48)**: $248 of the $430 "Heavy starting context" row (1) is definitions of MCP tools that were never called; the claude.ai Vercel server alone is $102. Disconnecting rarely used servers cuts every call. **Wrong working directory** may explain more of 1.
2. **Screenshot accumulation** and **Figma over-fetching**: the mobile/Figma sessions (BIT-landers-nsf-mobile) appear at the top of several leak rows.
3. **Fork context duplication**: multiplies the starting-context problem inside the $174 "Many agents" row (5, 13).
4. **Enable hooks (50)**: unlocks idle detection and per-session categorization.
