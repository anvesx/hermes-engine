# Tokenomics category audit

The dashboard categories that come from the core rows of `token-leak-categories.md` (core leaks 1-22, with 3a and 4a-4c), plus the other categories that have review comments, ordered by share of spend. The shares come from one developer's full local history (142 sessions, $963 at API list prices, 1h cache), computed with the same settings the dashboard sync uses. Rows overlap, so the shares add up to more than 100%.

### 01 Heavy starting context · Starting context and setup · 25.8%
**Current implementation:** starting context = first call's `input + cache_creation + cache_read` minus the first prompt. The excess over 10k tokens is charged at the cache-read price on every call in the session. The 10k baseline is below what Claude Code itself loads (minimum seen: 17k), so every session is flagged. Because the charge is multiplied by call count, long sessions count against the user rather than heavy setups.
**Ideal implementation:** (exact) starting context from the first assistant turn, as above. Metric per person: average starting context per session, % of sessions over a configurable threshold, and a breakdown into MCP tools, skill listings, memory/CLAUDE.md and system prompt, taken from the session's recorded tool list, skill listing and instruction files. Not flagged: a session that loads one MCP server and calls its tools.
**comments from dhruv:** CORRECT
**reply from Claude:** Agreed. Two details for the rewrite. The threshold goes in the config file; I'd start around 60k, since setups with deferred tools start at ~55k and Claude Code alone needs ~17k. And 48 and 49 become the breakdown of this number instead of separate costs, so the same tokens are counted once.

### 48 MCP tool schema bloat · Starting context and setup · 24.4% 
**Current implementation:** for each MCP server in the session's recorded tool list, sums the size of definitions for tools never called in that session and charges it on every call. A server is judged inside a single session, so any server not used in that session counts as waste, even one used every other day. The tokens are the same ones counted in 01, so the two rows double-count. Sizes are estimated from characters, and JSON schemas tokenize at a different rate: one session's estimate (~530k) is larger than its whole measured first-call context (450k).
**Ideal implementation:** (heuristic) per server, across the person's sessions over a window: servers loaded with full definitions but called in fewer than N% of sessions. Cost = their definition tokens × the sessions they loaded in, scaled so it never exceeds the measured starting context. Deferred tools (not loaded until searched) are excluded. Metric: share of starting context from rarely used servers. Not flagged: a server used a few times a week.
**comments from dhruv:** 

### 02 Cache-write premium · Prompt cache · 20.6%
**Current implementation:** for every cache write in every session and agent, charges the extra over the plain input price (0.25× input for 5m writes, 1× for 1h). This is the normal price of caching, and every session pays it. The same writes are also counted in 03, 04 and 21.
**Ideal implementation:** (exact) only the avoidable part: premium on writes caused by a choice, such as 1h writes in sessions whose calls never come more than 5 minutes apart (a 5m cache would have done), or writes that are never read back. Metric: avoidable premium as % of the person's input spend. Not flagged: a 1h write in a session with a 20-minute gap that is then read back.
**comments from dhruv:** Its not needed we will count the cache expired after break
**reply from Claude:** Agreed, drop it. The cache is how Claude Code works and the user can't choose the cache lifetime per write, so there is nothing for them to change. 04 will report the rewritten tokens and their premium itself.

### 03 Cold cache at session and agent start · Prompt cache · 20.2%
**Current implementation:** charges the full cost of the first cache write of every session and every new agent. Every session has to write its context once, so this measures how many sessions and agents someone starts, not waste. It is mostly the same tokens as 01.
**Ideal implementation:** can't be measured as waste on its own. Every session has to write its context once. The avoidable parts are how large that context is (01) and how many agents get started (05).
**comments from dhruv:** Its not needed we will count the cache expired after break
**reply from Claude:** Agreed, drop it. The size of what gets written stays visible in 01, and the number of agent starts in 05.

### 10 Restarting too often · Conversation history · 8.8%
**Current implementation:** when a session in the same project starts less than 60 minutes after the previous one ended and later makes an edit, every call before that first edit is charged. `/clear` starts a new session, so this charges the behaviour 06 and 08 recommend, and it charges all of the early work, including necessary reads.
**Ideal implementation:** (heuristic) count only re-exploration: in a session that starts soon after the last one, files read before the first edit that the previous session had already read. Metric: those re-read tokens as % of the person's input, and % of sessions affected. Not flagged: `/clear` followed by a new task that touches different files.
**comments from dhruv:** We will check initial prompts of a session and compare with 5 previous conversations if that can be implemented in same thread we will count whole current session at leak (we can use small model like hiku for this task)
**reply from Claude:** Doable with Haiku, with two changes. (1) Don't charge the whole session. The new session's real work would have cost tokens in the old thread too, and every call in a long thread costs more. The waste is the rebuild: calls before the first edit spent re-reading what the earlier session already had. (2) Compare with the earlier sessions in the same project within a time window (e.g. 24h), not just the last 5. Continuing only makes sense when the old thread is recent and not huge; if it was already over the 06 threshold, starting fresh was right. Haiku sees only the new first prompt and the last prompts of those sessions. This is the same Haiku pass as 08, 22 and 26 (see my reply on 08).

### 04 Cache expired after a break · Prompt cache · 8.3%
**Current implementation:** when a call follows a gap of at least the cache lifetime (default 1h, `--ttl`) and rewrites more than max(5k, half its context), charges the rewrite premium. This is close to correct. Problems: the lifetime comes from a flag rather than the per-entry `cache_creation` split (5m vs 1h), and it only reports dollars, with no per-person share.
**Ideal implementation:** (exact) for consecutive calls, detect the lifetime per write from the recorded 5m/1h split. If the gap is longer than that lifetime and the next call shows a large cache write instead of a read, count the rewritten tokens. Metric: premium tokens and premium as % of the person's input. Not flagged: a break followed by a small context (under a threshold), where the rewrite is cheap.
**comments from dhruv:** 

### 06 Long history replay · Conversation history · 7.8%
**Current implementation:** on every call, history above 100k tokens (context minus starting context) is charged at the cache-read price. A long, focused session scores as badly as a bloated one, and the row overlaps with 08, 11, 17 and 19.
**Ideal implementation:** (heuristic) average context per call and session duration. Flag only sessions that are both long-running and carry a very large average context. Compaction count is supporting info only. Metric: average context per call per person, % of sessions flagged. Not flagged: a long session kept lean with regular `/compact`.
**comments from dhruv:** Can we check if history is more than 600k tokens we can mark that as very large context
**reply from Claude:** Yes, with one change: set the threshold as a share of the model's context window in the config file, not as a fixed 600k. In the local data 91 of 152 sessions peak above 200k and only 9 above 600k. A model with a 200k window compacts long before 600k, so a fixed 600k would never flag it. Proposal: flag when the session's average context is above 60% of the window (600k on 1M models) and the session is long-running.

### 05 Many agents · Agents · 7.0%
**Current implementation:** all sub-agent spend in the session. This is a raw volume number: whoever uses agents most scores worst, whether or not the agents were useful.
**Ideal implementation:** (heuristic) sub-agent share = sub-agent tokens / session tokens. Flag sessions where the share is high and the agents did little. The agent result records each agent's tool-call count and total tokens, so "spawned to read one file" can be detected exactly. Metric: average sub-agent share per person and count of low-value spawns. Not flagged: an agent that runs 30 tool calls of research and returns a short summary.
**comments from dhruv:** I think we can improve here. It still feels wrong. 
**reply from Claude:** Agreed, the share metric is still a proxy. Revised proposal: judge each spawn, not the session. A spawn is low-value when the agent cost more than doing the same work in the main thread: its startup context plus all its calls, compared with what it actually read and reported back. Concretely, flag spawns with 1-2 tool calls, or whose startup context is many times what they read. Metric: % of spawns that are low-value, and the tokens in them. Drop the share metric. Correction to my audit: only 1 of 33 agent results in the local data records the tool count. The rest have to come from the agent's own transcript file (`subagents/agent-*.jsonl`), which the logs keep for each agent. 15's startup cost becomes the cost side of this check.

### 11 Stale tool results carried forward · Conversation history · 5.4%
**Current implementation:** every tool result still in context 30 calls later is charged at the cache-read price on every call until compaction. Every result in a long session counts, whether or not it is still relevant, so this mostly measures session length (again).
**Ideal implementation:** (heuristic) large tool results that are never used again. A result counts as used again if its file path, or identifiers from it, appear in later tool inputs or assistant text. Flag the ones still carried N calls later. Metric: share of context made of unused stale results, averaged per call. Not flagged: a file read early and edited 40 calls later.
**comments from dhruv:** but the thing is if a tool has been used wouldn't be the same context be passed on every next input, although the cashes ?
**reply from Claude:** Yes, exactly. Every tool result is sent again on every later call (read from the cache at ~10% of the input price) until `/clear` or compaction. That's why the current number only measures session length. And as you say on 19, one stale result can't be removed; the only actions are `/compact` and `/clear`. So I'd stop treating this as a separate leak and make it part of 06. When a session is flagged for very large context, show what that context is made of (stale tool results, screenshots, old replies), so "compact now" comes with a reason.

### 08 Sessions that never end · Conversation history · 5.0%
**Current implementation:** a "new task" begins at a `[tag]` or after 30 idle minutes. If more than 20k tokens of earlier history are still in context there, they are charged on every call of the new task. Nobody types tags (none in the data), so in practice this flags every coffee break, even when the user comes back to the same work.
**Ideal implementation:** (heuristic, soft signal) split the session per user prompt and decide whether each prompt continues the previous task. The cheap check: does it reference what was built earlier (same files, functions, endpoints)? The better check, behind a config flag: ask Haiku about the prompts only. Flag only many unrelated switches carried with a large context. Metric: unrelated switches per session, weighted by context. Not flagged: building an API and then its UI in one session.
**comments from dhruv:** I think I like the haiku version, so as we are thinking to do some more task with the haiku related to checking the prompts, we can combine them or maybe make a same category and then do a sub category under their please think what the best we can do
**reply from Claude:** Proposal: one Haiku "prompt check" pass per session, behind a config flag, shown as one dashboard group with sub-categories:
  - Unrelated task in a long thread (08): the prompt starts a new task while a large context is carried.
  - Correction (22): the prompt rejects the previous answer.
  - Could have continued an earlier session (10): a first prompt that continues a recent session.
  - Repeated task (26): a first prompt asking for the same thing as an earlier session.

  Haiku sees only prompt text (current and previous prompt, or first prompt and earlier sessions' prompts) and returns a small label. Results are cached locally by prompt hash, so re-runs are free. Labelling the local data once (~920 prompts) would cost under $1. Without the flag, each sub-category falls back to the cheap check (keyword or file overlap). Two decisions for you: call Haiku through `claude -p --model haiku` (uses the person's Claude Code login, no API key) or the API with a key; and whether sending prompt text to the model for this fits our privacy rule. It never goes into the sync payload.

### 09 No clear direction · Exploration and file reading · 3.3%
**Current implementation:** per task, if there were more than 15 reads/searches before the first edit, the full cost of every call after the 15th is charged. Tasks with no edit (investigations, reviews) are skipped entirely, a large codebase legitimately needs more reads, and the whole call cost is charged rather than just the reading.
**Ideal implementation:** (heuristic) dead-end exploration: files and searches before the first edit whose results are never used again (not edited, not cited, not read again). Metric: dead-end share of exploration tokens per task, averaged per person. Not flagged: a debugging task that reads 30 files and edits three of them after reading the call chain.
**comments from dhruv:** 

### 14 Large tool-call arguments · Tool and terminal output · 3.3%
**Current implementation:** any non-edit, non-agent tool call with more than 1k tokens of arguments: the output cost of writing them, plus re-reading them later. This counts legitimate output, such as Bash heredocs that create files and MCP calls that create documents or pages.
**Ideal implementation:** (heuristic) only arguments that repeat content already in context: large spans of the argument that match an earlier tool result or file content, where a path or reference would have done. Metric: duplicated argument tokens as % of output. Not flagged: a heredoc writing a new script.
**comments from dhruv:** I didn't get what is this category and what you are trying to implement in ideal implementation
**reply from Claude:** When Claude calls a tool, it writes the tool's input itself: the text of a Bash command, a script in a heredoc, the body of an MCP call. Those are output tokens (5x the input price), and they stay in context. This row flags every call whose input is over 1k tokens. In your data that is mostly Bash (393 calls, ~766k tokens, nearly all scripts and heredocs), plus ExitPlanMode (the plan text) and a few Shopify GraphQL mutations. That is almost all real work. The only wasteful case is Claude copying text that's already in context into an input, e.g. pasting a file's content into a curl body instead of passing the file path. That's what the ideal implementation meant: flag only the copied part. That case is rare and hard to detect reliably, so I'd drop this category.

### 20 Visual iteration loops · Images and browser · 2.2%
**Current implementation:** counts edit → screenshot cycles per task. Every cycle after the third is charged in full. UI polishing legitimately takes many cycles, and the task boundary is the 30-minute-gap guess.
**Ideal implementation:** (heuristic) cycles that made no progress: the screenshot is identical (same image hash) or nearly so to the previous one, or an edit reverts an earlier one. Metric: % of visual cycles without visible change, and their tokens. Not flagged: ten cycles, each showing a different change on screen.
**comments from dhruv:** yeah, ideal implementation looks fine, but I feel how you going to implement this. I want to know this feels little bit hard to implement technically.
**reply from Claude:** Two of the three parts are simple; one isn't.
  - Identical screenshot: each image arrives as base64 in the tool result, and we already hash it (28 does this today). The same hash as the previous screenshot in the cycle means nothing visible changed. Exact.
  - Reverted edit: an Edit whose new text equals the old text of an earlier Edit on the same file. Exact, from the tool inputs.
  - "Nearly identical" screenshots are the hard part. They need pixel decoding, which plain Python (no libraries, as the plugin requires) can do for PNG but not JPEG. I'd leave this out.

  So: a cycle is an edit followed by a screenshot (as today). A cycle made no progress if its screenshot has the same hash as the previous one, or its edit undoes an earlier one. Flag tasks with several no-progress cycles.

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

### 15 Agent startup cost · Agents · 1.1%
**Current implementation:** the full input cost of the first call of every agent after the first one. Every agent pays this, so it is raw volume, and it overlaps 03 and 05.
**Ideal implementation:** can't be measured as waste on its own. Startup tokens only mean something compared with what the agent then did, which is the low-value-spawn signal in 05.
**comments from dhruv:** okay, so in your opinion we need to delete this?
**reply from Claude:** Yes, remove it as a separate category. Its number becomes the cost side of the low-value-spawn check in 05.

### 24 Too much tool output · Tool and terminal output · 1.0%
**Current implementation:** non-shell, non-agent results over 4k tokens: the excess over 2k is carried until compaction. A large file the model needs in full gets flagged by size alone.
**Ideal implementation:** (heuristic) large results of which only a small part was used afterwards, e.g. a large read followed by one small edit and no other reference. Metric: unused share of large-result tokens. Not flagged: a large file read and then edited in many places.
**comments from dhruv:** let's keep this category as currently, what implemented.
**reply from Claude:** OK, the logic stays as it is. In the rewrite only the 4k/2k thresholds move to the config file, and the row is labelled heuristic.

### 22 Correction churn · Retries and rework · 0.7%
**Current implementation:** prompts matching a regex (`no`, `wrong`, `stop`, `don't`, `again`, `i said`…) charge the whole following turn. The regex catches instructions ("don't add tests", "stop the server") and charges new work as rework.
**Ideal implementation:** (heuristic) a correction is a prompt that rejects the previous answer. Detect it with the regex as a cheap pass, and Haiku on the prompt behind a flag. Charge only the work that was redone (edits to the same lines, reverted edits). Metric: % of prompts that are corrections, and redone tokens as % of output. Not flagged: "don't use semicolons" given as a new instruction at task start.
**comments from dhruv:** 

### 19 Screenshot accumulation · Images and browser · 0.6%
**Current implementation:** every image result is charged on every later call until compaction. Every screenshot is counted, so this is raw image usage.
**Ideal implementation:** (heuristic) image tokens still in context more than N calls after the image was last relevant (no image-related tool use since). Metric: stale image tokens as % of the person's context. Not flagged: one screenshot checked against the next two edits.
**comments from dhruv:** I'm not sure how you going to implement this. Also if we found this as a major category and try to solid, there is no way to actually remove some images from the context or any of the portion from the context. Either we need to clear the context or compact.
**reply from Claude:** Agreed, and that's the key point: images can't be removed one by one, and the only fixes are `/compact` and `/clear`. So this has no action of its own. I'd fold it into 06 the same way as 11. When a session is flagged for large context, show how much of it is screenshots, e.g. "40% of this context is screenshots from UI work that ended 60 calls ago: compact". Implementation: at each call, sum the image tokens still in context since the last compaction. We already size images from their pixel dimensions.

### 27 Failed, retried and polling calls · Retries and rework · 0.4%
**Current implementation:** three parts. (1) Error results: a share of the call's output plus the error text carried. (2) The same failing call 3+ times, with the whole call cost charged. (3) Identical call and identical result 3+ times. Problems: "failure" in (2) partly comes from a text regex ("not found", "error"), so ordinary grep output counts, and user permission denials count as waste.
**Ideal implementation:** (exact) only results the tool marked as errors, excluding user denials. Retries are the same tool and input failing again. Polling is identical input with an identical result. Metric: % of tool calls that fail or repeat, and their tokens. Not flagged: a failing test, then a fix, then a passing rerun.
**comments from dhruv:** 

### 39 Compaction cost · Conversation history · 0.3%
**Current implementation:** summary tokens at the output price plus the cache rewrite after each compaction. Compaction is the cure for bloated context, not the waste.
**Ideal implementation:** (exact, supporting info for 06) count auto-compactions that hit the context limit, since they point to bloat. Each compaction records whether it was manual or automatic and how large the context was. Metric: % of sessions with auto-compaction. Not flagged: a manual `/compact` between tasks.
**comments from dhruv:** I'm not sure how you're going to count this because we don't have a data in the local for getting auto compact information this is completely from my information. You can check on your own.
**reply from Claude:** The local logs do record it. Each compaction writes a `compact_boundary` entry with `compactMetadata.trigger` (`auto` or `manual`) and `preTokens`, the context size at that moment. In your local data all 12 compactions are `auto`, at roughly 200k-460k tokens. A manual `/compact` is recorded as `manual`. So counting auto-compactions per session is exact.

### 26 Repeated tasks across sessions · Conversation history · 0.1%
**Current implementation:** if a session's first prompt shares at least 60% of its words with an earlier session's first prompt in the same project, the whole session cost is charged. Template prompts ("continue", "review the PR") match, and a deliberate retry of a failed attempt is counted as waste.
**Ideal implementation:** (heuristic) the same request that redoes the same work: a matching first prompt plus edits to the same files with no change between the two sessions. Metric: % of sessions that repeat earlier work. Not flagged: a daily "run the test suite" prompt.
**comments from dhruv:** can I agree with you that this is how it should be implemented, but need to check how we are going to build this technically
**reply from Claude:** How it would be built: (1) Compare the session's first prompt with the first prompts of earlier sessions in the same project, using the Haiku check from 08 (or word overlap without the flag). (2) For a match, compare the files edited in both sessions, taken from the Edit/Write inputs. Flag only when both match: the same request, and mostly the same files edited again (e.g. 50%+ overlap). The logs can't say whether the first attempt's work was kept or thrown away, so this stays heuristic and is shown as "spend to review", not waste.

### 36 Wordy and repeated output · Model and output · 0.1%
**Current implementation:** several checks: Write over a file already read (a full-file rewrite), replies that restate the request, repeated 300+-character paragraphs, reprinted code blocks, and replies cut off at the output limit. The rewrite check flags genuine full rewrites.
**Ideal implementation:** (exact for rewrites, heuristic for the rest) a Write whose recorded patch changes only a small part of the file (it should have been an Edit), plus repeated paragraphs and code blocks. Metric: repeated output as % of output tokens. Not flagged: rewriting most of a file.
**comments from dhruv:** didn't get the point here
**reply from Claude:** The main check is about rewriting whole files. Claude replaced an existing file with Write when only a few lines changed, so it paid output tokens (5x the input price) for the whole file instead of a small Edit, e.g. rewriting a 400-line file to change 3 lines. The logs record each Write's diff, so we can tell how much actually changed. The other checks are smaller: a reply that restates the question, the same paragraph or code block printed twice, and a reply cut off at the output limit. The whole row is 0.1% of your spend. If you want fewer categories, keep only the rewrite check.

### 31 Duplicate reading across agents · Agents · 0.1%
**Current implementation:** a file read by one agent and then read again by a sibling agent, or by the parent after an agent read it. Re-reading is charged. A parent checking an agent's claim before editing is good practice.
**Ideal implementation:** (heuristic) sibling agents reading the same files (overlapping briefs), and parent re-reads not followed by an edit to that file. Metric: duplicate read tokens as % of agent read tokens. Not flagged: the parent reads a file an agent found and then edits it.
**comments from dhruv:** in this case, we cannot tell that if sibling agent reading the same file as another agent is leak because sometimes that agent might also need the context that another agent did, even if the tasks are parallel, we still sometimes require the same file to be read by both of the agents, and this also same for the parent agent to. I don't know. Either we need to remove this point completely. 
**reply from Claude:** Agreed, remove it. Both cases have legitimate reasons, and the logs can't tell them apart. It was also only 0.1% of spend.

### 42 Verbose agent reports and briefs · Agents · 0.0%
**Current implementation:** agent reports over 2.5k tokens (the excess over 1k is carried), and agent briefs over 1k tokens (output cost). A research agent asked for a full report is flagged.
**Ideal implementation:** (heuristic) report size relative to the agent's own work. Its recorded tool count and tokens give that ratio: a long report from a short job is padding. Metric: median report-to-work ratio per person. Not flagged: a long report from a 40-call investigation.
**comments from dhruv:** 

### 44 Re-learning the codebase · Exploration and file reading · 0.0%
**Current implementation:** files read before the first edit that at least 2 earlier sessions in the project also read before their first edit, charged as carried. Sessions don't share memory, so some re-reading is unavoidable.
**Ideal implementation:** (heuristic) the share of pre-edit exploration spent on files explored in 3+ recent sessions. That points to missing project notes (CLAUDE.md). Metric: % of exploration tokens on such files, per person. Not flagged: the first few sessions in a repo.
**comments from dhruv:** also, many people doesn't manage Claude MD and just boom the task with any random prompt on the same project, so I'm not sure how we can measure this that how much you spend on relearning the gold base, but in my opinion that it would be much larger if the project doesn't contain the memory files
**reply from Claude:** Agreed that's the likely cause, and the logs can show it. Each session records which instruction files were loaded (project CLAUDE.md, memory index, user file). So split sessions into projects with project notes and projects without, and report exploration before the first edit for each. Metric per person: average exploration tokens before the first edit, and % of their sessions in projects without notes. The dashboard can then say "sessions in projects without CLAUDE.md spent Nx more on exploration". That's a correlation, not proof, so it is labelled heuristic.

### 45 High effort on trivial turns · Model and output · 0.0%
**Current implementation:** a one-call turn with no tools and a reply of 300 tokens or less, where output minus the estimated reply exceeds 3k tokens. The excess over 1k is charged. Reasoning is guessed from character counts, although the transcript records thinking tokens exactly.
**Ideal implementation:** (heuristic) use the recorded thinking-token count. Flag short, tool-free turns whose reasoning is many times the reply. Metric: % of such turns and their reasoning tokens. Not flagged: a short answer to a hard question ("is this lock-free?").
**comments from dhruv:** 

### 47 Usage while idle · Retries and rework · 0.0%
**Current implementation:** prompts with no matching hook record within 15s count as not typed by the user, and their turn cost is charged. This only works for users with the hook installed.
**Ideal implementation:** (exact) every user entry records where the turn came from (typed, system, task notification, SDK, auto-continuation), so this works without the hook. Metric: share of tokens in turns not started by a person. Not flagged: a `/loop` or scheduled task the user set up on purpose, so show it as info rather than waste.
**comments from dhruv:** 

## Notes
- **Rows overlap heavily.** 01, 48 and 49 charge the same starting tokens. 02, 03 and 04 charge the same cache writes. 06, 08, 11 and 19 charge the same history. Each token should count toward one category, or the dashboard should stop presenting shares side by side.
- **The "carry" cost model favours short sessions.** Most rows charge an item on every later call until compaction. Any item in a long session costs more, so nearly every history and output row grows with session length rather than with bad practice.
- **Item sizes are estimates.** Sizes come from characters at a default rate (only 5 of 142 sessions calibrate their own). JSON schemas break the default: the MCP estimate exceeded a session's whole measured context. Label these rows heuristic and cap estimates at measured totals.
- **Task boundaries are guessed.** 08, 09, 12 and 20 split tasks on `[tag]` prefixes (unused in the data) or 30-minute gaps. Prompt-level continuation checks (example 6) would serve all of them.
- **Spend-to-review rows sit next to waste.** 02, 03, 05, 06, 15 and 26 are marked "review" in code (normal spend, not all waste), but the dashboard ranks them alongside the leaks with no distinction.
