# Tokenomics category audit

The 50 categories as the dashboard shows them, ordered by share of spend. The shares come from one developer's full local history (142 sessions, $963 at API list prices, 1h cache), computed with the same settings the dashboard sync uses. Rows overlap, so the shares add up to more than 100%.

### 01 Heavy starting context · Starting context and setup · 25.8%
**Current implementation:** starting context = first call's `input + cache_creation + cache_read` minus the first prompt. The excess over 10k tokens is charged at the cache-read price on every call in the session. The 10k baseline is below what Claude Code itself loads (minimum seen: 17k), so every session is flagged. Because the charge is multiplied by call count, long sessions count against the user rather than heavy setups.
**Ideal implementation:** (exact) starting context from the first assistant turn, as above. Metric per person: average starting context per session, % of sessions over a configurable threshold, and a breakdown into MCP tools, skill listings, memory/CLAUDE.md and system prompt, taken from the session's recorded tool list, skill listing and instruction files. Not flagged: a session that loads one MCP server and calls its tools.
**comments from dhruv:** CORRECT

### 48 MCP tool schema bloat · Starting context and setup · 24.4% 
**Current implementation:** for each MCP server in the session's recorded tool list, sums the size of definitions for tools never called in that session and charges it on every call. A server is judged inside a single session, so any server not used in that session counts as waste, even one used every other day. The tokens are the same ones counted in 01, so the two rows double-count. Sizes are estimated from characters, and JSON schemas tokenize at a different rate: one session's estimate (~530k) is larger than its whole measured first-call context (450k).
**Ideal implementation:** (heuristic) per server, across the person's sessions over a window: servers loaded with full definitions but called in fewer than N% of sessions. Cost = their definition tokens × the sessions they loaded in, scaled so it never exceeds the measured starting context. Deferred tools (not loaded until searched) are excluded. Metric: share of starting context from rarely used servers. Not flagged: a server used a few times a week.
**comments from dhruv:** 

### 02 Cache-write premium · Prompt cache · 20.6%
**Current implementation:** for every cache write in every session and agent, charges the extra over the plain input price (0.25× input for 5m writes, 1× for 1h). This is the normal price of caching, and every session pays it. The same writes are also counted in 03, 04 and 21.
**Ideal implementation:** (exact) only the avoidable part: premium on writes caused by a choice, such as 1h writes in sessions whose calls never come more than 5 minutes apart (a 5m cache would have done), or writes that are never read back. Metric: avoidable premium as % of the person's input spend. Not flagged: a 1h write in a session with a 20-minute gap that is then read back.
**comments from dhruv:** Its not needed we will count the cache expired after break

### 03 Cold cache at session and agent start · Prompt cache · 20.2%
**Current implementation:** charges the full cost of the first cache write of every session and every new agent. Every session has to write its context once, so this measures how many sessions and agents someone starts, not waste. It is mostly the same tokens as 01.
**Ideal implementation:** can't be measured as waste on its own. Every session has to write its context once. The avoidable parts are how large that context is (01) and how many agents get started (05).
**comments from dhruv:** Its not needed we will count the cache expired after break

### 10 Restarting too often · Conversation history · 8.8%
**Current implementation:** when a session in the same project starts less than 60 minutes after the previous one ended and later makes an edit, every call before that first edit is charged. `/clear` starts a new session, so this charges the behaviour 06 and 08 recommend, and it charges all of the early work, including necessary reads.
**Ideal implementation:** (heuristic) count only re-exploration: in a session that starts soon after the last one, files read before the first edit that the previous session had already read. Metric: those re-read tokens as % of the person's input, and % of sessions affected. Not flagged: `/clear` followed by a new task that touches different files.
**comments from dhruv:** We will check initial prompts of a session and compare with 5 previous conversations if that can be implemented in same thread we will count whole current session at leak (we can use small model like hiku for this task)

### 04 Cache expired after a break · Prompt cache · 8.3%
**Current implementation:** when a call follows a gap of at least the cache lifetime (default 1h, `--ttl`) and rewrites more than max(5k, half its context), charges the rewrite premium. This is close to correct. Problems: the lifetime comes from a flag rather than the per-entry `cache_creation` split (5m vs 1h), and it only reports dollars, with no per-person share.
**Ideal implementation:** (exact) for consecutive calls, detect the lifetime per write from the recorded 5m/1h split. If the gap is longer than that lifetime and the next call shows a large cache write instead of a read, count the rewritten tokens. Metric: premium tokens and premium as % of the person's input. Not flagged: a break followed by a small context (under a threshold), where the rewrite is cheap.
**comments from dhruv:** 

### 06 Long history replay · Conversation history · 7.8%
**Current implementation:** on every call, history above 100k tokens (context minus starting context) is charged at the cache-read price. A long, focused session scores as badly as a bloated one, and the row overlaps with 08, 11, 17 and 19.
**Ideal implementation:** (heuristic) average context per call and session duration. Flag only sessions that are both long-running and carry a very large average context. Compaction count is supporting info only. Metric: average context per call per person, % of sessions flagged. Not flagged: a long session kept lean with regular `/compact`.
**comments from dhruv:** Can we check if history is more than 600k tokens we can mark that as very large context

### 05 Many agents · Agents · 7.0%
**Current implementation:** all sub-agent spend in the session. This is a raw volume number: whoever uses agents most scores worst, whether or not the agents were useful.
**Ideal implementation:** (heuristic) sub-agent share = sub-agent tokens / session tokens. Flag sessions where the share is high and the agents did little. The agent result records each agent's tool-call count and total tokens, so "spawned to read one file" can be detected exactly. Metric: average sub-agent share per person and count of low-value spawns. Not flagged: an agent that runs 30 tool calls of research and returns a short summary.
**comments from dhruv:** I think we can improve here. It still feels wrong. 

### 11 Stale tool results carried forward · Conversation history · 5.4%
**Current implementation:** every tool result still in context 30 calls later is charged at the cache-read price on every call until compaction. Every result in a long session counts, whether or not it is still relevant, so this mostly measures session length (again).
**Ideal implementation:** (heuristic) large tool results that are never used again. A result counts as used again if its file path, or identifiers from it, appear in later tool inputs or assistant text. Flag the ones still carried N calls later. Metric: share of context made of unused stale results, averaged per call. Not flagged: a file read early and edited 40 calls later.
**comments from dhruv:** but the thing is if a tool has been used wouldn't be the same context be passed on every next input, although the cashes ?

### 08 Sessions that never end · Conversation history · 5.0%
**Current implementation:** a "new task" begins at a `[tag]` or after 30 idle minutes. If more than 20k tokens of earlier history are still in context there, they are charged on every call of the new task. Nobody types tags (none in the data), so in practice this flags every coffee break, even when the user comes back to the same work.
**Ideal implementation:** (heuristic, soft signal) split the session per user prompt and decide whether each prompt continues the previous task. The cheap check: does it reference what was built earlier (same files, functions, endpoints)? The better check, behind a config flag: ask Haiku about the prompts only. Flag only many unrelated switches carried with a large context. Metric: unrelated switches per session, weighted by context. Not flagged: building an API and then its UI in one session.
**comments from dhruv:** I think I like the haiku version, so as we are thinking to do some more task with the haiku related to checking the prompts, we can combine them or maybe make a same category and then do a sub category under their please think what the best we can do

### 07 Interrupted turns · Retries and rework · 4.9%
**Current implementation:** when the user interrupts a turn, every call from that turn's prompt up to the interrupt is charged. Interrupting a turn that is going the wrong way saves tokens, but this charges the user the most for interrupting late, and penalizes interrupting at all.
**Ideal implementation:** (heuristic) count only interrupted work that was then redone: an interrupt followed by a prompt that restates or corrects the same request, with edits to the same files. Metric: % of turns interrupted and redone, and the tokens of the discarded work. Not flagged: an interrupt in the first few calls that redirects the model.
**comments from dhruv:** 

### 09 No clear direction · Exploration and file reading · 3.3%
**Current implementation:** per task, if there were more than 15 reads/searches before the first edit, the full cost of every call after the 15th is charged. Tasks with no edit (investigations, reviews) are skipped entirely, a large codebase legitimately needs more reads, and the whole call cost is charged rather than just the reading.
**Ideal implementation:** (heuristic) dead-end exploration: files and searches before the first edit whose results are never used again (not edited, not cited, not read again). Metric: dead-end share of exploration tokens per task, averaged per person. Not flagged: a debugging task that reads 30 files and edits three of them after reading the call chain.
**comments from dhruv:** 

### 14 Large tool-call arguments · Tool and terminal output · 3.3%
**Current implementation:** any non-edit, non-agent tool call with more than 1k tokens of arguments: the output cost of writing them, plus re-reading them later. This counts legitimate output, such as Bash heredocs that create files and MCP calls that create documents or pages.
**Ideal implementation:** (heuristic) only arguments that repeat content already in context: large spans of the argument that match an earlier tool result or file content, where a path or reference would have done. Metric: duplicated argument tokens as % of output. Not flagged: a heredoc writing a new script.
**comments from dhruv:** I didn't get what is this category and what you are trying to implement in ideal implementation

### 20 Visual iteration loops · Images and browser · 2.2%
**Current implementation:** counts edit → screenshot cycles per task. Every cycle after the third is charged in full. UI polishing legitimately takes many cycles, and the task boundary is the 30-minute-gap guess.
**Ideal implementation:** (heuristic) cycles that made no progress: the screenshot is identical (same image hash) or nearly so to the previous one, or an edit reverts an earlier one. Metric: % of visual cycles without visible change, and their tokens. Not flagged: ten cycles, each showing a different change on screen.
**comments from dhruv:** yeah, ideal implementation looks fine, but I feel how you going to implement this. I want to know this feels little bit hard to implement technically.

### 49 Unused skills/plugins · Starting context and setup · 1.8%
**Current implementation:** listed skills and agent types not invoked in that session, carried on every call. As with 48, a session can't use every skill, so most skills are always "unused". The listing exists so the model can find skills, and the row double-counts 01.
**Ideal implementation:** (heuristic) across the person's sessions over a window: skills and plugins listed in every session but never invoked in N days. Cost = their listing tokens × sessions. Metric: share of starting context from unused listings. Not flagged: a skill used once a week.
**comments from dhruv:** 

### 13 Fork context duplication · Agents · 1.7%
**Current implementation:** any agent whose first call is above 50k tokens is charged (first context − 10k) on every one of its calls. With a heavy setup (01), every fresh agent starts above 50k, so this measures 01 again rather than forking.
**Ideal implementation:** (exact) compare an agent's starting context with the parent's context at spawn time and with a fresh agent's normal start. A fork is an agent that starts at roughly the parent's size. Metric: inherited tokens × the agent's calls, as % of the person's agent tokens. Not flagged: a fresh agent with a short brief.
**comments from dhruv:** 

### 12 Bigger model than needed · Model and output · 1.7%
**Current implementation:** two parts. First, tasks tagged as simple (`docs`, `rename`…) and run on Opus/Fable, priced against Sonnet. No tags exist in the data, so this part does nothing. Second, every sub-agent call on Opus/Fable, priced against Sonnet, which is the whole $16.62. Using Opus says nothing about waste.
**Ideal implementation:** (heuristic) flag an Opus/Sonnet turn as a small task when it has a short prompt, small output, few tool calls and tiny edits. Line counts come from each edit's recorded patch. Exclude planning turns (long reasoning, no edits). Metric: % of a person's Opus/Sonnet turns that look like small tasks, and the tokens spent on them. Not flagged: a short prompt that leads to a careful multi-file fix.
**comments from dhruv:** 

### 25 Noisy and repeated terminal output · Tool and terminal output · 1.4%
**Current implementation:** combines four checks. (1) Shell results over 4k tokens: the excess over 2k is carried. (2) Results where more than 50% of lines repeat. (3) The same traceback twice. (4) Unchanged lint output. Part 1 is size alone: a long failing test run that is needed in full gets flagged.
**Ideal implementation:** (heuristic) only noise: repeated lines, progress bars and unchanged reruns (same command, same output), measured as tokens. Metric: noise as % of the person's shell-output tokens. Not flagged: one long failing test output followed by a fix.
**comments from dhruv:** 

### 21 Cache not reused · Prompt cache · 1.1%
**Current implementation:** three parts. (1) Cache writes not read back within the lifetime, charged the premium. (2) Calls with more than 10k uncached input. (3) Calls too short to cache. Part 1 counts the last write of every session, which is never read by design.
**Ideal implementation:** (exact) writes not read before expiry, excluding each session's final call and the write just before a deliberate end. Metric: unread write tokens as % of the person's cache writes. Not flagged: the final turn of a session.
**comments from dhruv:** 

### 15 Agent startup cost · Agents · 1.1%
**Current implementation:** the full input cost of the first call of every agent after the first one. Every agent pays this, so it is raw volume, and it overlaps 03 and 05.
**Ideal implementation:** can't be measured as waste on its own. Startup tokens only mean something compared with what the agent then did, which is the low-value-spawn signal in 05.
**comments from dhruv:** okay, so in your opinion we need to delete this?

### 24 Too much tool output · Tool and terminal output · 1.0%
**Current implementation:** non-shell, non-agent results over 4k tokens: the excess over 2k is carried until compaction. A large file the model needs in full gets flagged by size alone.
**Ideal implementation:** (heuristic) large results of which only a small part was used afterwards, e.g. a large read followed by one small edit and no other reference. Metric: unused share of large-result tokens. Not flagged: a large file read and then edited in many places.
**comments from dhruv:** let's keep this category as currently, what implemented.

### 22 Correction churn · Retries and rework · 0.7%
**Current implementation:** prompts matching a regex (`no`, `wrong`, `stop`, `don't`, `again`, `i said`…) charge the whole following turn. The regex catches instructions ("don't add tests", "stop the server") and charges new work as rework.
**Ideal implementation:** (heuristic) a correction is a prompt that rejects the previous answer. Detect it with the regex as a cheap pass, and Haiku on the prompt behind a flag. Charge only the work that was redone (edits to the same lines, reverted edits). Metric: % of prompts that are corrections, and redone tokens as % of output. Not flagged: "don't use semicolons" given as a new instruction at task start.
**comments from dhruv:** 

### 19 Screenshot accumulation · Images and browser · 0.6%
**Current implementation:** every image result is charged on every later call until compaction. Every screenshot is counted, so this is raw image usage.
**Ideal implementation:** (heuristic) image tokens still in context more than N calls after the image was last relevant (no image-related tool use since). Metric: stale image tokens as % of the person's context. Not flagged: one screenshot checked against the next two edits.
**comments from dhruv:** I'm not sure how you going to implement this. Also if we found this as a major category and try to solid, there is no way to actually remove some images from the context or any of the portion from the context. Either we need to clear the context or compact.

### 23 Agents racing the cache · Prompt cache · 0.5%
**Current implementation:** agents that start within 10s of each other, both writing more than 5k, are charged the whole write premium. Only their shared prefix is duplicated, not the whole write.
**Ideal implementation:** (exact) for agents started within the cache-creation window, the shared prefix tokens written more than once (the smallest sibling write), at the write premium. Metric: duplicate prefix writes as % of agent cache writes. Not flagged: agents started a minute apart.
**comments from dhruv:** 

### 17 Old replies replayed · Conversation history · 0.5%
**Current implementation:** every assistant reply's text is charged on every later call until compaction. That is just what a conversation costs.
**Ideal implementation:** not measurable as waste on its own. The wasteful part (repeated or reprinted replies) is covered by 36.
**comments from dhruv:** 

### 18 Clarification loops · Retries and rework · 0.4%
**Current implementation:** the full cost of every call that asks the user a question (`AskUserQuestion`). This penalizes asking, which is often the right thing to do.
**Ideal implementation:** (heuristic) repeated clarification: two or more question rounds in one task before any work, or the same question asked twice. Metric: % of tasks with repeated clarification. Not flagged: one up-front question that settles the approach.
**comments from dhruv:** 

### 16 Model switch rewrote the cache · Prompt cache · 0.4%
**Current implementation:** a large cache write right after the model changes is charged the rewrite premium. The mechanics are correct (exact), but switching to Opus for one hard step is a fair choice.
**Ideal implementation:** (exact) rewritten tokens on a switch, as % of the person's input. Flag only back-and-forth switching (switching back within N turns) on a large context. Not flagged: one switch at a natural break, or on a small context.
**comments from dhruv:** 

### 34 Broad or unbounded searches · Exploration and file reading · 0.4%
**Current implementation:** search results over 100 lines (the excess fraction is carried), plus Grep/Glob with no path or type limit returning more than 1k tokens. This is reasonable, but it counts size only, whether or not the results were used.
**Ideal implementation:** (heuristic) search output beyond N lines, plus unbounded searches that were immediately followed by a narrower search. Metric: excess search tokens as % of search output. Not flagged: an unbounded search in a small repo that returns 20 lines.
**comments from dhruv:** 

### 30 Whole-file reads · Exploration and file reading · 0.4%
**Current implementation:** reads without offset/limit that return more than 5k tokens: the excess over 2k is carried. The model often needs the whole file to edit it safely.
**Ideal implementation:** (heuristic) whole-file reads where everything that follows touches only a small region (one small edit or a grep of a few lines, no other use). Metric: unused share of whole-file read tokens. Not flagged: reading a whole file and then refactoring many parts of it.
**comments from dhruv:** 

### 27 Failed, retried and polling calls · Retries and rework · 0.4%
**Current implementation:** three parts. (1) Error results: a share of the call's output plus the error text carried. (2) The same failing call 3+ times, with the whole call cost charged. (3) Identical call and identical result 3+ times. Problems: "failure" in (2) partly comes from a text regex ("not found", "error"), so ordinary grep output counts, and user permission denials count as waste.
**Ideal implementation:** (exact) only results the tool marked as errors, excluding user denials. Retries are the same tool and input failing again. Polling is identical input with an identical result. Metric: % of tool calls that fail or repeat, and their tokens. Not flagged: a failing test, then a fix, then a passing rerun.
**comments from dhruv:** 

### 32 Agent coordination chatter · Agents · 0.3%
**Current implementation:** every message sent to or received from another agent, charged in full. This is raw volume of agent teamwork.
**Ideal implementation:** (heuristic) messages that carry nothing new: duplicates or near-duplicates of earlier messages, or status pings with no change. Metric: share of message tokens that repeat. Not flagged: one handoff message with results.
**comments from dhruv:** 

### 39 Compaction cost · Conversation history · 0.3%
**Current implementation:** summary tokens at the output price plus the cache rewrite after each compaction. Compaction is the cure for bloated context, not the waste.
**Ideal implementation:** (exact, supporting info for 06) count auto-compactions that hit the context limit, since they point to bloat. Each compaction records whether it was manual or automatic and how large the context was. Metric: % of sessions with auto-compaction. Not flagged: a manual `/compact` between tasks.
**comments from dhruv:** 

### 28 Repeated screenshots · Images and browser · 0.2%
**Current implementation:** three checks: an identical image seen again, a screenshot taken right after another one, and the same screenshot after a failed browser action. The back-to-back check flags normal navigation (click, then screenshot each page).
**Ideal implementation:** (exact) identical or near-identical images only (same hash). Metric: duplicate image tokens as % of image tokens. Not flagged: screenshots of different pages during navigation.
**comments from dhruv:** 

### 35 Bloated JSON and query results · Tool and terminal output · 0.2%
**Current implementation:** three parts. (1) JSON or database results over 4k tokens: the excess over 2k is carried. (2) Results whose JSON keys and wrappers make up more than half the text. (3) Database query output over 4k tokens. Part 1 is size alone.
**Ideal implementation:** (heuristic) the structure overhead and unused fields: JSON tokens spent on keys and wrappers, plus fields never referenced afterwards. Metric: overhead as % of the person's JSON result tokens. Not flagged: a schema dump that the next edit is based on.
**comments from dhruv:** 

### 26 Repeated tasks across sessions · Conversation history · 0.1%
**Current implementation:** if a session's first prompt shares at least 60% of its words with an earlier session's first prompt in the same project, the whole session cost is charged. Template prompts ("continue", "review the PR") match, and a deliberate retry of a failed attempt is counted as waste.
**Ideal implementation:** (heuristic) the same request that redoes the same work: a matching first prompt plus edits to the same files with no change between the two sessions. Metric: % of sessions that repeat earlier work. Not flagged: a daily "run the test suite" prompt.
**comments from dhruv:** 

### 40 Git and GitHub output · Tool and terminal output · 0.1%
**Current implementation:** several checks: git diffs over 4k tokens, lockfile/generated diffs, verbose git log, an unchanged git status, and large PR or issue dumps. Lockfile diffs and repeated status are good checks. The size checks flag a PR review that needs the whole diff.
**Ideal implementation:** (heuristic) only avoidable parts: lockfile/generated diff tokens, unchanged repeated status, and full log metadata when a short format would have done. Metric: avoidable git tokens as % of git output. Not flagged: reading a full diff for a code review.
**comments from dhruv:** 

### 29 Progress narration · Model and output · 0.1%
**Current implementation:** in any message that also calls a tool, text beyond 50 tokens is charged as output and carried. Explaining a plan before a risky step is useful.
**Ideal implementation:** (heuristic) narration share of output tokens per person. Flag only text that repeats what the tool call itself states, or more than N tokens per step on average. Not flagged: a one- or two-sentence status line before a destructive command.
**comments from dhruv:** 

### 36 Wordy and repeated output · Model and output · 0.1%
**Current implementation:** several checks: Write over a file already read (a full-file rewrite), replies that restate the request, repeated 300+-character paragraphs, reprinted code blocks, and replies cut off at the output limit. The rewrite check flags genuine full rewrites.
**Ideal implementation:** (exact for rewrites, heuristic for the rest) a Write whose recorded patch changes only a small part of the file (it should have been an Edit), plus repeated paragraphs and code blocks. Metric: repeated output as % of output tokens. Not flagged: rewriting most of a file.
**comments from dhruv:** 

### 33 Large images and PDFs · Images and browser · 0.1%
**Current implementation:** several checks: images over 1,200 tokens (the excess, at input price once), PDF reads carried, and a document read both as page images and as text. This is reasonable. The single-image size check is a weak signal, because the API already downscales.
**Ideal implementation:** (exact) documents read twice in two forms, and multi-page PDFs read in full when only some pages were used afterwards. Metric: duplicate document tokens as % of image/PDF tokens. Not flagged: a single design mock at full resolution.
**comments from dhruv:** 

### 31 Duplicate reading across agents · Agents · 0.1%
**Current implementation:** a file read by one agent and then read again by a sibling agent, or by the parent after an agent read it. Re-reading is charged. A parent checking an agent's claim before editing is good practice.
**Ideal implementation:** (heuristic) sibling agents reading the same files (overlapping briefs), and parent re-reads not followed by an edit to that file. Metric: duplicate read tokens as % of agent read tokens. Not flagged: the parent reads a file an agent found and then edits it.
**comments from dhruv:** 

### 46 Tool discovery and skill loading · Starting context and setup · 0.0%
**Current implementation:** three checks: more than 2 tool-search calls per session, reads of skill supporting documents, and skill bodies over 3k tokens. Tool search is how deferred tools get loaded, and deferring tools cuts starting context about 3× (~55k vs ~188k median), so this penalizes the cheaper setup.
**Ideal implementation:** (exact) tool searches whose loaded tools are never called, and skills invoked but never acted on. Metric: unused discovery tokens per session. Not flagged: a tool search followed by a call to the found tool.
**comments from dhruv:** 

### 37 Web pages and search results · Web research · 0.0%
**Current implementation:** several checks: page fetches over 4k tokens, searches with more than 10 results, the same URL fetched again, duplicate passages and sources, and prompts with an attached document or over 10k tokens. This mostly works, but the large-prompt check doesn't belong here.
**Ideal implementation:** (heuristic) duplicate fetches and duplicate content as tokens, measured as % of web tokens. Pasted documents are not web research and don't belong in this measure. Not flagged: fetching one doc page to answer an API question.
**comments from dhruv:** 

### 41 Dependency, vendor and generated files · Exploration and file reading · 0.0%
**Current implementation:** reads of files under `node_modules`, `dist`, `vendor` and similar, plus lockfiles and minified files, and search output with 5+ lines from those folders. Deliberately reading a library's source to check its API gets flagged.
**Ideal implementation:** (heuristic) search output from dependency or build folders (an unscoped search), plus generated-file reads. Exclude targeted reads of a specific dependency file. Metric: share of search and read tokens from those folders. Not flagged: one Read of a library file to check a function signature.
**comments from dhruv:** 

### 42 Verbose agent reports and briefs · Agents · 0.0%
**Current implementation:** agent reports over 2.5k tokens (the excess over 1k is carried), and agent briefs over 1k tokens (output cost). A research agent asked for a full report is flagged.
**Ideal implementation:** (heuristic) report size relative to the agent's own work. Its recorded tool count and tokens give that ratio: a long report from a short job is padding. Metric: median report-to-work ratio per person. Not flagged: a long report from a 40-call investigation.
**comments from dhruv:** 

### 44 Re-learning the codebase · Exploration and file reading · 0.0%
**Current implementation:** files read before the first edit that at least 2 earlier sessions in the project also read before their first edit, charged as carried. Sessions don't share memory, so some re-reading is unavoidable.
**Ideal implementation:** (heuristic) the share of pre-edit exploration spent on files explored in 3+ recent sessions. That points to missing project notes (CLAUDE.md). Metric: % of exploration tokens on such files, per person. Not flagged: the first few sessions in a repo.
**comments from dhruv:** 

### 38 Copied history (pastes, transcripts, forks) · Conversation history · 0.0%
**Current implementation:** three checks: the same 400+-character paragraph pasted again in a later session, prompts that look like a pasted chat transcript, and forked sessions (sharing message ids) charged for the inherited context. These are reasonable signals.
**Ideal implementation:** (exact for forks and repeated pastes, heuristic for transcripts) tokens of repeated pastes and inherited fork context, as % of the person's input. Not flagged: a resumed session continuing its own work.
**comments from dhruv:** 

### 43 Repeated reads of unchanged files · Exploration and file reading · 0.0%
**Current implementation:** a Read of the same path and range, with no Edit of that file since, is charged as carried. It shows 25 instances at $0.00 because Claude Code already returns a short "unchanged" stub for these. It also misses changes made through Bash and counts re-reads after compaction, which are necessary.
**Ideal implementation:** (exact) re-reads that returned full content although the file was unchanged, excluding reads after a compaction. Metric: % of read tokens. Not flagged: re-reading after a compaction or after `git checkout`.
**comments from dhruv:** 

### 45 High effort on trivial turns · Model and output · 0.0%
**Current implementation:** a one-call turn with no tools and a reply of 300 tokens or less, where output minus the estimated reply exceeds 3k tokens. The excess over 1k is charged. Reasoning is guessed from character counts, although the transcript records thinking tokens exactly.
**Ideal implementation:** (heuristic) use the recorded thinking-token count. Flag short, tool-free turns whose reasoning is many times the reply. Metric: % of such turns and their reasoning tokens. Not flagged: a short answer to a hard question ("is this lock-free?").
**comments from dhruv:** 

### 47 Usage while idle · Retries and rework · 0.0%
**Current implementation:** prompts with no matching hook record within 15s count as not typed by the user, and their turn cost is charged. This only works for users with the hook installed.
**Ideal implementation:** (exact) every user entry records where the turn came from (typed, system, task notification, SDK, auto-continuation), so this works without the hook. Metric: share of tokens in turns not started by a person. Not flagged: a `/loop` or scheduled task the user set up on purpose, so show it as info rather than waste.
**comments from dhruv:** 

### 50 No visibility · Observability · unmeasurable
**Current implementation:** shows how many sessions have hook data. It is not a cost.
**Ideal implementation:** can't be measured as waste. It describes data coverage, not token use.

## Notes
- **Rows overlap heavily.** 01, 48 and 49 charge the same starting tokens. 02, 03, 04 and 21 charge the same cache writes. 06, 08, 11, 17 and 19 charge the same history. Each token should count toward one category, or the dashboard should stop presenting shares side by side.
- **The "carry" cost model favours short sessions.** Most rows charge an item on every later call until compaction. Any item in a long session costs more, so nearly every history and output row grows with session length rather than with bad practice.
- **Item sizes are estimates.** Sizes come from characters at a default rate (only 5 of 142 sessions calibrate their own). JSON schemas break the default: the MCP estimate exceeded a session's whole measured context. Label these rows heuristic and cap estimates at measured totals.
- **Task boundaries are guessed.** 08, 09, 12 and 20 split tasks on `[tag]` prefixes (unused in the data) or 30-minute gaps. Prompt-level continuation checks (example 6) would serve all of them.
- **Spend-to-review rows sit next to waste.** 02, 03, 05, 06, 15, 17, 18, 26 and 29 are marked "review" in code (normal spend, not all waste), but the dashboard ranks them alongside the leaks with no distinction.
