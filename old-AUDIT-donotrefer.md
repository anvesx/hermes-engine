# Tokenomics category audit

Step 1 of the category rewrite. No code was changed. This covers every leak detector in `plugins/token-metrics/scripts/`: the 26 core ids in `leak_report.py`, the 109 canvas "A rows" in `leak_extra.py`, and the 50 curated categories in `leak_categories.py` that sum them. It ends with a proposed final list of 11 categories, plus the decisions that need approval before Step 2.

## 1. Data used

- **Sample:** one developer's local history. That is 206 transcript files, and the last 30 days hold 138 sessions and $891 of API-equivalent spend. Claude Code versions run from 2.1.282 to 2.1.310, and 99% of main-session spend is on Opus 5.5. This sample is enough to check field names and catch false positives. It is not enough to set team thresholds, and it can't validate "model too large" for people who already use Sonnet or Haiku.
- **Current report:** I ran `leak_report.py --days 30` and `--all` on the same data. The costs quoted below come from those runs.
- **Privacy:** this repo is public, so this file quotes only aggregates. It has no prompts, project names or paths.

## 2. Field names, checked against real files

| Expected (brief) | Actual | Notes |
|---|---|---|
| `message.model` | ✅ `message.model` | `<synthetic>` entries are written by Claude Code itself (errors, placeholders). Skip them. `requestedModel` is also recorded. |
| `message.usage.*` | ✅ `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens` | One API response is written as several `assistant` entries, one per content block, all with the same `message.id`. Dedupe by `message.id` (the code already does), or every count is multiplied. In 53 of 15,236 entries the usage differs within one id. Take the last entry. |
| (not in brief) | `usage.cache_creation.ephemeral_1h_input_tokens` / `ephemeral_5m_input_tokens` | **The cache TTL is recorded on every call.** No config guess is needed. Here 90% of writes are 1h and 10% are 5m, mixed within the same sessions. |
| (not in brief) | `usage.output_tokens_details.thinking_tokens`, entry-level `perTurnEffort` / `effort` | **Thinking tokens and effort level are exact.** They are present on 13,941 of 15,236 calls. Today the code estimates thinking as `output − reply text ÷ chars-per-token`. |
| `timestamp` | ✅ ISO-8601 | |
| `isSidechain` | ✅ | Sub-agent turns live in separate files, `<session>/subagents/agent-*.jsonl`. Every message entry there has `isSidechain: true`. Main-session files have `false`. |
| `tool_use.input.file_path` | ✅ for Read/Edit/Write | `Agent` input has `subagent_type`, `prompt` and `description`. **Forks are identifiable exactly** with `subagent_type: "fork"`. |
| (not in brief) | `toolUseResult.structuredPatch`, `originalFile` on Edit/Write | **The exact lines changed by each edit are recorded.** This is what makes the "tiny edit" signal in category 1 possible. |
| compaction entries | `system` / `compact_boundary` with `compactMetadata.trigger` (`auto`/`manual`) and `preTokens`. There is also an `isCompactSummary` user entry. | |
| (not in brief) | `attachment` entries: `prompt_snapshot` (system prompt + every tool definition, MCP tools carry `server`), `instructions` (CLAUDE.md/memory text), `skill_listing`, `agent_listing_delta`, `mcp_instructions_delta`, `deferred_tools_delta`, `hook_*` | These make the starting-context breakdown possible. Since roughly 2.1.310, MCP tools are **deferred**: their definitions are no longer sent and snapshots list only built-in tools. |
| (not in brief) | `api-request` (with `cacheControl` TTLs and breakpoints), `cost-state` (Claude Code's own `totalCostUSD`) | These appear only in recent versions. `cost-state` can serve as a cross-check for our price model. |

Gotchas that affect the detectors:
- There are no `Grep` or `Glob` tool calls in current transcripts, because search runs through `Bash`. Detectors keyed on those tool names (A73, A79) are effectively dead.
- Bash's non-zero exit codes come back as `is_error: true`. That covers 107 of 189 error results here: failing tests, `grep` with no match, and so on. Any detector that counts `is_error` as a "failed call" counts normal work.
- Item sizes are estimated with characters per token. Only 4 of 138 sessions had enough samples to calibrate their own ratio, so the rest use 2.37. On tool-definition JSON that default **overestimates by about 1.4×**: one session's snapshot estimates 578k tokens, but its exact first call was 418k.

## 3. Problems that cut across categories

1. **The four biggest rows are fixed costs of using Claude Code, not behaviour.** "Heavy starting context" (25.6%), "MCP schema bloat" (24.0%), "Cache-write premium" (21.1%) and "Cold cache" (20.7%) flag all, or nearly all, 138 sessions:
   - The starting-context baseline is 10k tokens. The smallest real first call in the data is 17k and the median is 171k.
   - Every cache write and every first write is unavoidable. Caching is what makes reads 10× cheaper.
2. **The carry cost model behaves like a raw count.** Most detectors charge an item × the cache-read price × every later call until compaction. Long sessions therefore inflate every category at once. A heavy user with long sessions scores worse everywhere, even when each item is reasonable.
3. **The waste index double-counts.** `stats.py` sums the shares of all non-review curated rows, but row 48 (MCP) and row 49 (skills) are subsets of row 1. In this data rows 1 + 48 alone add up to about 50% of spend.
4. **Rows contradict each other.** Row 8 ("Sessions that never end") penalises one long session, and row 10 ("Restarting too often") penalises a new session started within an hour of the last one. A developer can't satisfy both.
5. **Good habits are punished.** Interrupting a wrong turn, asking a clarifying question, writing a detailed sub-agent brief, verifying UI with a screenshot after an edit, and starting fresh for a new task are each charged as waste.
6. **Claude Code internals are charged to people.** Cache breakpoints, tool ordering, system-prompt timestamps and concurrent cache writes describe the harness, not the developer.
7. **Thresholds are scattered.** About 55 constants sit across two files, and some are copied in both (`START_BASELINE`, `DEP_DIRS`, `EDIT_TOOLS`, `BIG`).
8. **There are no tests** and **no definitions**, beyond one-line descriptions in `token-leak-categories.md`.

## 4. The 50 curated categories

Failure types: **NM** not measurable, **WP** wrong proxy, **RC** raw count, **FP** false positive on legitimate work, **OK** fine. "→ F*n*" points to the proposed final category in section 6. Share = share of 30-day spend in the current report.

| # | Category (share) | Supposed to measure | What the code does now | Failure | Rec | Reason |
|---|---|---|---|---|---|---|
| 1 | Heavy starting context (25.6%) | Sessions that load a huge context before the first ask | (first-call ctx − 10k) × read price × every call in the session | RC, FP | **Rewrite → F2** | A 10k baseline is below the 17k floor, so 138/138 sessions are flagged, and the cost grows with session length. Use exact start size, a % over threshold and a breakdown. |
| 2 | Cache-write premium (21.1%) | Paying extra for cache writes | The write premium on *every* cache write | WP | **Drop** | It's the price of caching, which saves money overall, and it flags every session. It isn't anything a developer does. |
| 3 | Cold cache at session/agent start (20.7%) | Paying for the first cache write | The full first write of every session and agent | WP | **Drop** | Unavoidable. Agent starts are covered by F4. |
| 4 | Cache expired after a break (7.5%) | Re-caching after a break | Rewrites > max(5k, 50% of ctx) after a gap ≥ the `--ttl` flag | OK (minor) | **Rewrite → F3** | The logic is right. Fixes: read the TTL per call from `cache_creation` instead of a flag, report a % of input, and fold in the other causes of a rewrite. |
| 5 | Many agents (5.8%) | Sub-agent overuse | Sums *all* helper spend | RC | **Rewrite → F4** | All sub-agent use is charged. The rewrite uses share plus low-value spawns, as in example 4. |
| 6 | Long history replay (7.9%) | Bloated long-running threads | History > 100k × read price on every call | RC | **Merge → F5** | A long, focused task is flagged as much as a bloated one. |
| 7 | Interrupted turns (4.5%) | Regenerating after partial answers | The whole cost of every turn the user interrupted | FP | **Merge → F10** | Interrupting early *saves* tokens. Only interrupt-then-redo is rework. |
| 8 | Sessions that never end (4.9%) | Unrelated tasks piled into one thread | A new "task" is a `[tag]` or a 30-minute gap; charges carried context > 20k | WP | **Rewrite → F6** | A lunch break mid-feature counts as a new task. Nothing checks whether tasks are related. |
| 9 | No clear direction (3.4%) | Unfocused exploration | > 15 reads/searches before the first edit in a task | FP, RC | **Merge → F11** | Debugging and unfamiliar code legitimately need reading. The count ignores repo size. |
| 10 | Restarting too often (9.5%) | Rebuilding context after needless fresh starts | All pre-edit cost of any session starting < 1h after the last one | FP | **Drop** | Starting fresh for a new task is the recommended habit, and this contradicts row 8. |
| 11 | Stale tool results carried forward (5.5%) | Old results kept in context | Every result still present 30+ calls later | RC | **Drop (→ F5)** | It describes how context works, and any long session is flagged. F5 covers the behaviour. |
| 12 | Bigger model than needed (1.5%) | Opus/Sonnet on work Haiku could do | Opus on `[docs]`/`[chore]`-style tags, plus *every* Opus helper | WP | **Rewrite → F1** | Needs hand tags and flags every Opus sub-agent (the brief's example). |
| 13 | Fork context duplication (1.1%) | Forks inheriting the parent's context | Any helper whose first call is > 50k | FP | **Merge → F4** (exact sub-signal) | The median sub-agent starts at 91k on its own, so 24 agents are flagged with **zero forks** in the data. Use `subagent_type == "fork"`. |
| 14 | Large tool-call arguments (3.3%) | Bloated tool inputs | Non-Edit tool inputs > 1k tokens | FP | **Drop** | Large inputs are usually the work itself: scripts via heredoc, pages and file contents. |
| 15 | Agent startup cost (0.8%) | Repeated agent setup | The first-call cost of every helper but the first | RC | **Drop (→ F4)** | Every spawn is charged. F4's metric includes startup. |
| 16 | Model switch rewrote the cache (0.4%) | Switching models mid-session | A big rewrite on the call after the model changed | OK | **Merge → F3** (cause) | Exact and user-driven. Keep it as a cause inside F3. |
| 17 | Old replies replayed (0.5%) | Replaying past answers | Every assistant text block × later calls | WP | **Drop** | Inherent to any conversation. |
| 18 | Clarification loops (0.4%) | Ambiguous prompts | The cost of every `AskUserQuestion` call | FP | **Drop** | Asking before acting is good behaviour. |
| 19 | Screenshot accumulation (0.7%) | Screenshots bloating context | Every image × later calls | RC | **Drop (→ F8/F9)** | Every screenshot is charged. Duplicates go to F8, oversized ones to F9. |
| 20 | Visual iteration loops (2.4%) | Flailing UI tweaks | > 3 edit→screenshot cycles per task | FP | **Drop** | That cycle is the correct way to verify UI, and productive and flailing loops can't be told apart. |
| 21 | Cache not reused (1.2%) | Cache writes wasted | Writes not read back within the TTL; uncached calls; prefixes below the minimum | WP | **Drop** | The last write before every pause is never read back, which is inherent. The other two found 0 and are harness-controlled. |
| 22 | Correction churn (0.8%) | Rework from bad prompts or answers | Turns whose prompt starts with no/don't/stop/again/… | FP, low recall | **Merge → F10** | Matched 10 of 798 prompts, including "don't …" instructions that aren't corrections. Charges the correction turn, not the wasted turn. |
| 23 | Agents racing the cache (0.6%) | Parallel cache writes | Sibling agents starting ≤ 10s apart | WP | **Drop** | Parallelism is a legitimate latency trade-off, and it's harness behaviour. |
| 24 | Too much tool output (1.0%) | Oversized tool results | Non-shell results > 4k tokens | RC | **Rewrite → F9** | Size alone flags needed content. The rewrite looks for *unfiltered* calls. |
| 25 | Noisy and repeated terminal output (1.4%) | Build/log spam | Bash > 4k; repeated lines, tracebacks, lint output | RC + OK parts | **Merge → F9 / F8** | Size moves to F9 and identical repeats to F8. |
| 26 | Repeated tasks across sessions (0.1%) | Redoing the same task | First prompts with ≥ 60% word overlap → whole session charged | FP | **Drop** | Retrying a failed task is legitimate. It's a weak proxy that found 3 instances. |
| 27 | Failed, retried and polling calls (0.3%) | Retry loops | Every `is_error` result + same failing input 3× + same call/result 3× | FP + OK part | **Rewrite → F7** | Keep only the identical-failure loop. Any `is_error` includes failing tests and empty greps. Polling goes to F8. |
| 28 | Repeated screenshots (0.2%) | Unchanged screenshots | Back-to-back screenshots, identical hashes, retakes after errors | FP + OK part | **Merge → F8** (identical hash only) | Back-to-back shots are normal during navigation. |
| 29 | Progress narration (0.1%) | Chatty status text | > 50 tokens of text in tool-calling messages | FP | **Drop** | Brief status updates are expected, and the cost is negligible. |
| 30 | Whole-file reads (0.4%) | Reading a file for one section | Unsliced `Read` > 5k tokens | FP | **Merge → F9** | A file you go on to edit is needed whole. F9 excludes that case. |
| 31 | Duplicate reading across agents (0.1%) | Agents duplicating work | Siblings reading the same path; parent re-reading after a helper | FP | **Drop (→ F4 supporting)** | A parent re-reading before editing is necessary. Sibling overlap stays as info. |
| 32 | Agent coordination chatter (0.2%) | Inter-agent messages | Every `SendMessage` | RC | **Drop** | Charges any coordination. |
| 33 | Large images and PDFs (0.1%) | Oversized media | Images > 1.2k tokens; PDFs; PDF read twice | RC | **Merge → F9** | A normal full screenshot is about 1.5k tokens, so every one is flagged. |
| 34 | Broad or unbounded searches (0.4%) | Searches without scope | > 100 result lines; Grep/Glob with no path | WP | **Merge → F9** | The Grep/Glob tools no longer exist. Fold into the unfiltered-output check. |
| 35 | Bloated JSON and query results (0.2%) | Oversized structured output | JSON/DB results > 4k; wrapper-heavy JSON | RC | **Merge → F9** | Same signal as F9, by source. |
| 36 | Wordy and repeated output (0.1%) | Verbose model output | Full `Write` on a read file; restating; repeated paragraphs/code; `max_tokens` | FP / ~0 | **Drop** | A rewrite is sometimes right, and the rest found ~$0. `structuredPatch` feeds F1 instead. |
| 37 | Web pages and search results (0.0%) | Over-fetching web content | 7 web detectors | ~0 | **Merge → F9 / F8** | Large pages go to F9, re-fetches of the same URL to F8, and the rest are dropped. |
| 38 | Copied history (0.0%) | Pasted transcripts, forks | Repeated pastes; transcript-like prompts; `--resume` forks | ~0, FP | **Drop** | $0.01 total, and resuming a session is legitimate. |
| 39 | Compaction cost (0.3%) | Cost of compacting | Summary + rewrite after each compaction | WP | **Drop (→ F5 supporting)** | Compaction is the remedy, not the leak. The count and trigger become supporting info. |
| 40 | Git and GitHub output (0.1%) | Big diffs, logs, PR dumps | 6 git/gh detectors | RC | **Merge → F9 / F8** | Large output goes to F9, unchanged `git status` to F8. |
| 41 | Dependency, vendor and generated files (0.0%) | Reading `node_modules`, lockfiles | Path regex on reads and search hits | OK | **Merge → F9** (exact tag) | A valid exact signal, too small to stand alone. |
| 42 | Verbose agent reports and briefs (0.0%) | Bloated agent hand-offs | Reports > 2.5k; briefs > 1k | FP | **Drop (→ F4 supporting)** | Detailed briefs are good practice, since a sub-agent starts with no context. |
| 43 | Repeated reads of unchanged files (0.0%) | Re-reading the same file | Same path/offset/limit with no edit between | OK (bug) | **Merge → F8** | Exact, but it ignores compaction: a re-read after compaction is needed. |
| 44 | Re-learning the codebase (0.0%) | Knowledge not saved between sessions | Pre-edit reads of files 2+ earlier sessions explored | OK | **Merge → F11** | A behavioural signal (missing CLAUDE.md), weak in this sample. |
| 45 | High effort on trivial turns (0.0%) | Over-thinking simple asks | Estimated reasoning > 3k on a short no-tool reply | WP (estimate) | **Merge → F1** | Thinking tokens and effort are now exact fields. Use them. |
| 46 | Tool discovery and skill loading (0.0%) | Tool search, skill docs | ToolSearch > 2 per session; skill doc reads; skill bodies > 3k | ~0 | **Drop (→ F2 breakdown)** | Negligible. Skill sizes go into the F2 breakdown. |
| 47 | Usage while idle (0.0%) | Unattended token burn | Turns without a typed prompt (needs hooks) | WP | **Drop** | Scheduled loops are deliberate. 0 findings. |
| 48 | MCP tool schema bloat (24.0%) | Unused MCP tools sent every call | Unused tool chars ÷ 2.37 × every call's read price | RC, overestimate | **Merge → F2** (breakdown) | It is part of row 1 and counted twice in the waste index. The 2.37 ratio overestimates about 1.4× on JSON. It is zero in Claude Code versions that defer tools. |
| 49 | Unused skills/plugins (1.9%) | Unused listings sent every call | Listing lines never invoked × later calls | RC | **Merge → F2** (breakdown) | Part of row 1. |
| 50 | No visibility | Sessions without hook data | Coverage stat | not a cost | **Drop** as a category | Show hook coverage as metadata. |

## 5. Every detector (core ids and canvas A rows)

The curated table above already covers each detector's logic, so this table gives the destination and reason per detector. "→ F*n*" means the signal survives inside that final category.

### Core detectors (`leak_report.LEAKS`)

| Id | Name | Failure | Rec | Reason |
|---|---|---|---|---|
| 1 | Heavy starting context | RC, FP | Rewrite → F2 | See curated row 1 |
| 2 | Sessions that never end | WP | Rewrite → F6 | See curated row 8 |
| 3 | Losing the cache | OK (parent of 3a) | Rewrite → F3 | Keep the cause attribution (break, model switch, prefix change); exclude post-compaction rewrites |
| 3a (26) | Cache expired after a break | OK | → F3 | See curated row 4 |
| 4 | Many agents | RC | Rewrite → F4 | |
| 4a (23) | Fork context duplication | FP | → F4 | Detect forks by `subagent_type` |
| 4b (24) | Overlapping agents | OK (tiny) | → F4 supporting | |
| 4c (25) | Verbose agent reports | FP | Drop | 0 findings; long reports are often the point |
| 5 | No clear direction | FP, RC | → F11 | |
| 6 | Bigger model than needed | WP | Rewrite → F1 | |
| 7 | Too much tool output | RC | → F9 | |
| 8 | Wordy responses | FP | Drop | |
| 9 | Retry loops | OK | **Keep → F7** | Identical failing input repeated is exact. Add "no edit between attempts". |
| 10 | Usage while idle | WP | Drop | |
| 11 | No visibility | not a cost | Drop (metadata) | |
| 12 | MCP tool schema bloat | RC | → F2 breakdown | |
| 13 | Unused skills/plugins | RC | → F2 breakdown | |
| 14 | Screenshot accumulation | RC | Drop | |
| 15 | Repeated tasks across sessions | FP | Drop | |
| 16 | Failed/denied tool calls | FP | Drop | Non-zero exits are normal work |
| 17 | Noisy commands | RC | → F9 | |
| 18 | High effort on trivial turns | WP | → F1 | Use exact `thinking_tokens` / `perTurnEffort` |
| 19 | Compaction cost | WP | Drop (→ F5 info) | |
| 20 | Correction churn | FP | → F10 | |
| 21 | Visual iteration loops | FP | Drop | |
| 22 | Re-learning the codebase | OK | → F11 | |

### Canvas A rows that are measured today (`leak_extra.ADDITIONAL`)

| Row | Name | 30-day | Failure | Rec | Reason |
|---|---|---|---|---|---|
| A1 | Long single-thread history replay | $70.04 | RC | → F5 | |
| A5 | Old tool results carried into later turns | $48.81 | RC | Drop | Inherent to context |
| A6 | Previous answers replayed | $4.42 | WP | Drop | Inherent |
| A7 | Repeatedly pasted background | $0.01 | OK, ~0 | Drop | Negligible |
| A8 | Transcripts copied between chats | 0 | ~0 | Drop | Never fires |
| A9 | Conversation forks | 0 | FP | Drop | `--resume`/fork is legitimate |
| A10 | Frequent fresh starts | $84.85 | FP | Drop | Contradicts F6, punishes a good habit |
| A14 | Overlapping directory instructions | 0 | OK, ~0 | → F2 breakdown (lint note) | Exact text match, but never fires |
| A16 | Duplicate rules across layers | 0 | OK, ~0 | → F2 breakdown (lint note) | Same |
| A17 | Always-loaded project guidance | $7.35 | RC | → F2 breakdown | Size of CLAUDE.md/memory, not waste in itself |
| A18 | Stale auto-memory entries | 0 | OK, ~0 | Drop | Never fires |
| A19 | Excessive few-shot examples | $0.01 | ~0 | Drop | Mostly harness text |
| A21 | Missing prompt caching | 0 | WP | Drop | Harness-controlled |
| A22 | Cold-cache requests | $184.59 | WP | Drop | Unavoidable |
| A24 | Prefixes below cache minimum | 0 | WP | Drop | Harness-controlled |
| A25 | Timestamps in stable prefixes | 0 | WP | Drop | Harness behaviour |
| A26 | Changing system-prompt content | 0 | WP | → F3 cause | Exact; recorded as a cause, not scored |
| A27 | Changing tool definitions | 0 | OK | → F3 cause | User adds/removes MCP servers mid-session |
| A29 | Unstable tool ordering | 0 | WP | Drop | Harness behaviour |
| A30 | Model switch rewrites cache | $3.88 | OK | → F3 cause | |
| A34 | Concurrent cache writes | $5.09 | WP | Drop | |
| A35 | Cache writes never reused | $10.31 | WP | Drop | Last write before every pause is inherent |
| A37 | Cache-write premium | $187.94 | WP | Drop | |
| A38 | Effort change invalidates cache | 0 | OK | → F3 cause | User action (`/effort`) |
| A40 | Org/workspace switch | 0 | OK | → F3 cause | User action |
| A45 | Replanning after minor updates | 0 | FP | Drop | 5+ todo updates is normal on long tasks |
| A52 | Repeating the question | 0 | ~0 | Drop | |
| A53 | Repeating explanations | 0 | ~0 | Drop | |
| A54 | Progress narration | $0.60 | FP | Drop | |
| A58 | Reprinting artifacts | 0 | ~0 | Drop | |
| A60 | Truncated answers | 0 | OK, ~0 | Drop | `max_tokens` stops never occur |
| A65 | Tool discovery calls | $0.04 | FP | Drop | ToolSearch is how deferred tools load |
| A66 | Large tool-call arguments | $29.36 | FP | Drop | |
| A68 | Large invoked skill bodies | $0.24 | RC | → F2 breakdown | |
| A69 | Skill supporting-doc reads | 0 | FP | Drop | Skills are meant to load these on demand |
| A70 | MCP/hook context injection | $1.42 | RC | → F2 breakdown | |
| A71 | Whole-file reads | $3.19 | FP | → F9 | Exclude files then edited |
| A72 | Repeated reads of unchanged files | $0.00 | OK (bug) | → F8 | Respect compaction |
| A73 | Broad repository searches | $3.40 | RC | → F9 | |
| A76 | Dependency/vendor source | $0.12 | OK | → F9 tag | Exact path match |
| A77 | Generated files | 0 | OK | → F9 tag | |
| A79 | Unbounded searches | 0 | dead | Drop | Grep/Glob tools gone |
| A82 | Repeated tracebacks | $0.00 | OK | → F8 | Identical output |
| A84 | Repeated lint output | 0 | OK | → F8 | |
| A87 | Repeated log lines | $2.97 | OK | → F9 | Large, low-information output |
| A91 | Large git diffs | $0.78 | RC | → F9 | Unfiltered `git diff` |
| A92 | Lockfile diffs | 0 | OK | → F9 tag | |
| A93 | Verbose git log | 0 | OK | → F9 | `git log` without `--oneline` etc. is "unfiltered" |
| A94 | Repeated git status | 0 | OK | → F8 | |
| A95 | Full PR discussions | 0 | RC | → F9 | |
| A96 | Full issue histories | 0 | RC | → F9 | |
| A98 | Large JSON responses | $1.82 | RC | → F9 | |
| A99 | Large DB results | 0 | RC | → F9 | |
| A100 | JSON wrapper overhead | $0.04 | ~0 | Drop | |
| A101 | Full web pages | $0.07 | RC | → F9 | |
| A103 | Too many search results | $0.06 | ~0 | Drop | WebSearch result count is not user-set |
| A104 | Duplicate web sources | 0 | ~0 | Drop | |
| A105 | Re-fetching unchanged pages | $0.06 | OK | → F8 | |
| A107 | Overlapping retrieval chunks | $0.00 | ~0 | Drop | |
| A109 | Whole documents attached | 0 | FP | Drop | Attaching a doc is often the task |
| A110 | Re-retrieval after compaction | 0 | FP | Drop | Re-fetching after compaction is necessary |
| A111 | Large image payloads | $0.55 | RC | → F9 | Images above threshold only |
| A112 | Repeated unchanged screenshots | $0.17 | OK | → F8 | |
| A114 | Back-to-back screenshots | $2.09 | FP | Drop | Normal during navigation |
| A115 | Multi-page PDFs | $0.00 | RC | → F9 | |
| A116 | PDF as images + text | 0 | ~0 | Drop | |
| A117 | OCR + text duplicate | 0 | ~0 | Drop | |
| A120 | Screenshot retakes after errors | 0 | ~0 | → F8 | Covered by identical hash |
| A121 / A122 / A127 | Same as 4a / 4b / 4c | — | — | Follow 4a / 4b / 4c | |
| A124 | Verbose agent briefs | $0.03 | FP | Drop | |
| A125 | Agent startup instructions | $7.50 | RC | Drop (→ F4 metric) | |
| A126 | Agent coordination chatter | $2.22 | RC | Drop | |
| A128 | Parent re-reads after worker | $0.44 | FP | Drop | |
| A131 | Clarification loops | $3.62 | FP | Drop | |
| A134 | Interrupted turns | $40.04 | FP | → F10 | Only interrupt-then-redo |
| A135 | Invalid structured outputs | $0.06 | OK, ~0 | → F7 | Schema errors repeated are retry loops |
| A136 | Unchanged-state polling | $0.02 | OK | → F8 | Size-weighted, so small polls cost ~0 |
| A138 | Scheduled tasks repeating analysis | 0 | ~0 | Drop | |

### Canvas A rows marked unmeasurable

All of these are **dropped (NM)**. Three groups:

- **Needs a judgment of relevance (no log signal):** A3 obsolete requirements, A4 abandoned approaches, A20 conflicting instructions, A44 repeated reasoning, A46 alternative approaches, A47 self-critique cycles, A48 model hand-off reconstruction, A55 excessive examples, A56 unsolicited variants, A59 duplicate output formats, A102 web boilerplate, A108 irrelevant passages, A113 full-screen vs region screenshots, A119 irrelevant images in batches, A129 review rounds, A130 agents continuing after done, A132 missing acceptance criteria. A Haiku classifier could approximate some of them, but each would be a new heuristic with no ground truth. Not worth it until the core list is trusted.
- **Needs controlled experiments:** A42 excessive extended thinking, A49 duplicate execution after a model switch, A50 tokenizer differences. (A42's raw input, thinking tokens, is now exact and feeds F1. "Excessive" still needs an outcome measure.)
- **Harness internals or calls not in transcripts:** A28 edited earlier messages, A31 breakpoints on changing content, A32 stable content outside the cache, A33 breakpoint lookback, A36 warmup requests, A39 tool-choice changes, A43 replayed thinking, A137 model-powered hooks, A140 background analysis calls. Recent versions record `api-request` with cache breakpoints, so A28/A31–A33 are now *partly* measurable, but they describe Claude Code's behaviour, which a developer can't change.

## 6. Proposed final list: 11 categories

E = exact, H = heuristic. The 6 brief examples are F1–F6. F7–F11 are what survives from the rest. Full definitions, formulas and blind spots go in `CATEGORIES.md` in Step 2. This is the approval-level summary.

| # | Category | Type | Signal | Metric per person | Absorbs | Not flagged (legit case) |
|---|---|---|---|---|---|---|
| F1 | **Model too large** | H | Opus/Sonnet turns (main and sub-agent) with a short prompt, small output, few tool calls and tiny exact edits (`structuredPatch` lines). Planning turns (long reasoning, no edits) are excluded. Exact `thinking_tokens`/effort is a secondary signal. | % of Opus/Sonnet turns that look small; tokens and $ on them; $ at Haiku price | #6, #18, A42 input | A 2-line fix whose turn needed deep reasoning: reasoning above threshold excludes it. Counts only small *tasks*, since switching models mid-session itself costs a cache rewrite (F3). |
| F2 | **Starting context** | E | First main-thread call of each session (real start, even if before the report window): `input + cache_creation + cache_read` | Average starting context; % of sessions over threshold; breakdown by system prompt + built-in tools / MCP tools (by server) / CLAUDE.md + memory / skills / agents / MCP instructions / hooks | #1, #12, #13, A14, A16, A17, A68, A70 | A small setup is below threshold. The breakdown is the exact total split in proportion to the recorded attachments, so the 1.4× size overestimate cancels out. |
| F3 | **Cache premium after breaks** | E | Consecutive calls in one stream (main or one sub-agent) with gap > that call's TTL (from `cache_creation` 1h/5m split, config fallback) **and** `cache_creation` ≥ threshold share of ctx. Causes recorded: break / model switch / effort change / tools changed / org switch. | Premium tokens; premium as % of total input; $ (write − read price) | #3, 3a, A26, A27, A30, A38, A40 | A break on a small context falls under the min-size threshold. Rewrites right after a compaction go to F5 info, not here. |
| F4 | **Sub-agent overuse** | H | Sub-agent share = sidechain tokens ÷ session tokens. A low-value spawn is an agent with ≤ N tool calls (e.g. one Read) whose startup tokens dwarf what it read. Exact forks (`subagent_type: fork`) starting large are supporting info. | Average sub-agent share; low-value spawns per session (and %) | #4, 4a, 4b, A121, A122, A125 | Parallel Explore agents doing real work (many calls each) are not low-value. |
| F5 | **Session hygiene** | H | Per session: average ctx per main call, plus active duration / days spanned. Flag sessions that are both long-running and carry a very large average ctx. Compactions (auto/manual, `preTokens`) are info only. | Average ctx per call; # and % of sessions flagged | A1, A5 (info), #19 (info) | A long but lean session, or one kept small with regular `/compact`, is not flagged. |
| F6 | **Unrelated tasks in one session** | H, soft | One chunk per user prompt. Continuity check: shared identifiers (files touched, symbols, endpoints) with earlier chunks, plus an optional Haiku check behind a config flag. Flag only on many unrelated switches **and** large context carried at them. | Unrelated switches per session, weighted by carried ctx. Soft signal, kept out of the waste index. | #2 | API then UI for the same feature: shared identifiers mean it continues. |
| F7 | **Retry loops** | E | The same tool with identical input failing ≥ 3 times in a row, with **no edit in between** | % of tool calls inside retry loops; tokens of attempts beyond the second | #9, A135 | TDD (test → edit → test) has an edit in between. |
| F8 | **Duplicate tool output** | E | A tool result byte-identical to an earlier one still in context (same stream, no compaction in between), above a minimum size: unchanged file re-read, `git status`, screenshot, lint output, URL re-fetch, polling | Duplicate tokens ÷ all tool-result tokens; tokens carried | A72, A82, A84, A94, A105, A112, A120, A136 | Re-reading after an edit or a compaction. Small polls are weighted by size, so they cost ~0. |
| F9 | **Unfiltered large tool output** | H | Results above threshold from calls with no limiting: Read without offset/limit, shell without `head`/`tail`/`grep`/`--oneline`/`-q`, full web pages, large MCP JSON. Exact tag: dependency/build/generated paths. | Share of tool-result tokens from unfiltered large results, by source | #7, #17, A71, A73, A76, A77, A87, A91–A99, A101, A111, A115 | A whole-file read of a file then edited in the same task is excluded. |
| F10 | **Rework after corrections** | H | A user turn that corrects or undoes the previous one (tightened pattern, optional Haiku check), or an interrupt followed by a re-prompt. The waste counted is the *previous* turn's tokens. | % of user turns that are corrections; rework tokens | #20, A134 | "Now also add X" is iteration, not correction. An interrupt with no redo isn't counted. |
| F11 | **Repeated codebase exploration** *(provisional)* | H | Files read before the first edit that ≥ N earlier sessions of the same project also read before theirs, excluding files edited in this session | % of sessions that re-learn; tokens of repeated exploration per session | #5, #22 | First visit to a codebase; reading the file you're about to change. Keep only if it fires on team data, since it barely fires here. |

What disappears: 39 of the 50 curated rows, all 29 "unmeasurable" A rows, and every detector that charges a fixed cost of using Claude Code.

## 7. Decisions needed before Step 2

1. **What "tokens" means in shares.** Cache reads are about 95% of raw tokens but cost 0.1× the input price, so a share of raw tokens is dominated by cheap re-reads. **Recommendation:** compute shares on cost-weighted tokens (API list price) and display raw token counts beside them.
2. **The Haiku classifier (F6, F10).** The plugin is stdlib-only and has no API key. Option A shells out to `claude -p --model haiku`. That runs on the user's own plan, costs tokens and is slow over long histories. Option B leaves it out of v1 and ships the cheap identifier and pattern checks only. **Recommendation:** B now, with the config flag stubbed.
3. **The leaderboard baseline.** Changing definitions breaks the improvement score in `score.ts`, which compares the current `waste_index` with each user's first two weeks under the old definitions. Category ids change too, and the badges reference ids `"1"` and `"4"`. **Recommendation:** new category ids (`F1`…`F11` or slugs), bump `SCHEMA`, let the next sync re-send full history under the new definitions (it already sends all weeks), and recompute baselines. Waste index = sum of non-soft category shares, which no longer double-count.
4. **The legacy `--all` canvas list.** **Recommendation:** delete `leak_extra.py`'s detectors and the curated mapping instead of keeping them behind a flag. They stay in git history, and keeping them would mean maintaining two sets of numbers.
5. **Config file format.** **Recommendation:** `leak_config.py`, a sibling module holding plain constants, synced with the other scripts. It can be imported without a parser, and an optional JSON override sits next to it in `~/.claude/metrics/` for per-team tuning.
6. **Tests.** **Recommendation:** stdlib `unittest`, with hand-made JSONL fixtures under `plugins/token-metrics/tests/fixtures/`. Each category gets at least one should-flag and one should-not-flag case, and the legitimate cases in section 6 become the should-not-flag fixtures.
7. **Thresholds.** **Recommendation:** pick initial values from this sample's distributions (e.g. the starting-context threshold near the p75 of first-call context, not 10k), mark them provisional, and re-tune once two or three more people's research exports are pooled (`research.py merge`).

Waiting for approval of the list in section 6 and the decisions in section 7 before writing any code.
