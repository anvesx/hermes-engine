# Token Leak Categories

Reference for the `token-metrics:leak-report` categories: what each one catches, how it is detected, and ideas not built yet.

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
| **Large pastes** | Logs or code pasted straight into the prompt | User message token size |
| **Figma over-fetching** | `get_design_context` on large parent frames instead of child nodes | Node size and repeated calls on the same file |
| **Abandoned sessions** | Spend that ends with no edits, commits, or deploys | Sessions with zero write actions |


---

## Additional categories (A rows)

The canvas's "Additional categories" section, in the report's second table as A<canvas row>. 60 are measured from transcripts, 3 share a core row's measure, and 46 are unmeasurable and shown with the reason instead of $0.00. Detection logic is in `plugins/token-metrics/scripts/leak_extra.py`; A30, A72, A76 and A135 are recorded by the core detectors in `leak_report.py`.

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
| A14 | Overlapping directory-level instructions | Persistent instructions and memory | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A16 | Duplicate rules across instruction layers | Persistent instructions and memory | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A17 | Irrelevant always-loaded project guidance | Persistent instructions and memory | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A18 | Stale auto-memory entries | Persistent instructions and memory | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A19 | Excessive few-shot examples | Persistent instructions and memory | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A20 | Conflicting instructions causing corrective turns | Persistent instructions and memory | Unmeasurable: needs a labelled review of what was relevant or necessary (all corrections are counted in #20) |
| A21 | Missing prompt caching where supported | Cache misses and invalidation | Measured |
| A22 | Cold-cache requests | Cache misses and invalidation | Measured (spend to review) |
| A24 | Prefixes below cache eligibility thresholds | Cache misses and invalidation | Measured |
| A25 | Timestamps inside otherwise stable prefixes | Cache misses and invalidation | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A26 | Changing system-prompt content | Cache misses and invalidation | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store (counted in #3 as 'context changed') |
| A27 | Changing loaded tool definitions | Cache misses and invalidation | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store (counted in #3 as 'context changed') |
| A28 | Editing earlier conversation messages | Cache misses and invalidation | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A29 | Unstable tool serialization or ordering | Cache misses and invalidation | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A30 | Switching models with no reusable cache on the receiving model | Cache misses and invalidation | Measured |
| A31 | Cache breakpoints on changing content | Cache overhead and configuration | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A32 | Stable content outside cached prefixes | Cache overhead and configuration | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A33 | Cache breakpoint lookback limits | Cache overhead and configuration | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
| A34 | Concurrent requests before cache creation completes | Cache overhead and configuration | Measured |
| A35 | Cache writes never reused | Cache overhead and configuration | Measured |
| A36 | Repeated cache warmup requests | Cache overhead and configuration | Unmeasurable: these model calls are not recorded in transcripts |
| A37 | Cache-write pricing premiums | Cache overhead and configuration | Measured (spend to review) |
| A38 | Thinking or effort changes invalidating cached context | Cache overhead and configuration | Unmeasurable: depends on settings or provider scope that transcripts don't record |
| A39 | Tool-choice or web-tool configuration changes | Cache overhead and configuration | Unmeasurable: depends on settings or provider scope that transcripts don't record |
| A40 | Cache isolation across providers or workspaces | Cache overhead and configuration | Unmeasurable: depends on settings or provider scope that transcripts don't record |
| A42 | Excessive extended-thinking generation | Model selection and reasoning | Unmeasurable: needs matched runs with independent acceptance checks |
| A43 | Replayed thinking blocks where preserved | Model selection and reasoning | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
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
| A68 | Large invoked skill bodies | Tools, MCP, skills, and plugins | Unmeasurable: skill bodies are injected outside tool results; not identifiable in transcripts |
| A69 | Unnecessary skill supporting-document reads | Tools, MCP, skills, and plugins | Measured (spend to review) |
| A70 | Verbose plugin or hook context injection | Tools, MCP, skills, and plugins | Unmeasurable: needs the request payload (system prompt, tools, instructions), which transcripts don't store |
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
| A104 | Duplicate sources containing the same information | Web research and retrieval | Unmeasurable: needs a labelled review of what was relevant or necessary |
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
| A116 | PDF page-image processing alongside extracted text | Images, PDFs, and browser interaction | Unmeasurable: needs a labelled review of what was relevant or necessary |
| A117 | Duplicate OCR and document-text inputs | Images, PDFs, and browser interaction | Unmeasurable: needs a labelled review of what was relevant or necessary |
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
| A138 | Scheduled tasks repeating unchanged analysis | Retries, automation, and context rebuilding | Unmeasurable: needs hook data plus a comparison of each run's inputs |
| A140 | Background session-analysis model calls | Retries, automation, and context rebuilding | Unmeasurable: these model calls are not recorded in transcripts |

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
