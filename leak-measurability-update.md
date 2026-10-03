# Leak measurability update

What changed in `token-metrics` 1.4.0: which leak categories can now be measured from transcripts, which still can't, and why. Numbers are from 163 sessions, 2026-09-01 to 2026-10-02, API-equivalent spend $1,703.41.

## Summary

- **19 categories moved from unmeasurable to measured**: core #12 and #13 (curated rows 48 and 49) and 17 canvas A rows.
- **29 A rows are still unmeasurable**, plus #11 No visibility, which is a coverage gap rather than a cost. #10 Usage while idle only needs hook data.
- **The biggest new finding:** #48 MCP tool schema bloat costs **$248.34 (14.6% of spend)**, the 4th largest of the 50 rows. It is the definitions of MCP tools that are sent on every call but never called.

| Canvas section | Before | After |
|---|---|---|
| Core leaks unmeasurable | #12, #13 (and #10 without hooks, #11) | #10 without hooks, #11 |
| A rows measured | 60 | 77 |
| A rows sharing a core row's measure | 3 | 3 |
| A rows unmeasurable | 46 | 29 |

## Where the new data comes from

The report used to read only messages and tool results. Newer Claude Code versions also write `attachment` entries into every transcript, and the parser now reads them:

| Attachment | What it holds | Used by |
|---|---|---|
| `prompt_snapshot` | The system prompt and every tool definition (name, description, schema) | #12, A19, A25, A26, A27, A29 |
| `instructions` | Full text of each loaded `CLAUDE.md` (`Project`) and memory file (`AutoMem`) | A14, A16, A17, A18, A19 |
| `skill_listing`, `agent_listing_delta` | The skill and agent-type listings | #13 |
| `mcp_instructions_delta`, `hook_*` | MCP server instructions and hook-injected context | A70 |
| `credential_org` | The organization (workspace) the session runs under | A40 |
| meta message linked to a Skill call | The invoked skill's body | A68 |

Coverage: 154 of 163 sessions record prompt snapshots. Sessions from older Claude Code versions are skipped for these rows.

## MCP tool schema bloat (#48) by server

The cost of each server's tools that a session never called, re-read on every call:

| MCP server | Est. cost | Sessions |
|---|---|---|
| claude_ai_Vercel | $102.33 | 117 |
| claude_ai_Gmail | $24.53 | 107 |
| claude-in-chrome | $22.11 | 154 |
| claude_ai_Slack | $20.15 | 110 |
| firebase | $13.06 | 26 |
| plugin_figma_figma | $9.22 | 120 |
| claude_ai_Google_Calendar | $8.40 | 107 |
| claude_ai_Google_Drive | $7.98 | 110 |

The median session carries ~91k tokens of MCP tool definitions. The Vercel server alone is 212 tools, about 140k tokens, and was never called in these sessions. Disconnecting servers you rarely use cuts the cost of every call.

#49 Unused skills/plugins (listed skills and agent types never invoked) is $15.60.

## Newly measured

| Row | Leak | How it is detected | 30-day result |
|---|---|---|---|
| #12 | MCP tool schema bloat | Tokens of each MCP server's tools the session (or its helpers) never called, on every main call until the tools change | $248.34 |
| #13 | Unused skills/plugins | Listing entries for skills never invoked (Skill tool or slash command) and agent types never used, carried until compaction | $15.60 |
| A14 | Overlapping directory-level instructions | Lines repeated between project `CLAUDE.md` files at different directory levels | $0.00 |
| A16 | Duplicate rules across instruction layers | Lines repeated between layers (project, local, user, memory) | $0.00 |
| A17 | Irrelevant always-loaded project guidance | Project and local guidance above 2k tokens (spend to review) | $7.51 |
| A18 | Stale auto-memory entries | Memory index lines linking to memory files that no longer exist | $0.00 |
| A19 | Excessive few-shot examples | `<example>` blocks beyond 2 per tool description, system prompt or instruction file | $0.01 |
| A25 | Timestamps inside otherwise stable prefixes | Cache rewrite after the system prompt changed only in its digits | $0.00 |
| A26 | Changing system-prompt content | Cache rewrite after the recorded system prompt changed | $0.00 |
| A27 | Changing loaded tool definitions | Cache rewrite after the recorded tool definitions changed | $1.25 |
| A29 | Unstable tool serialization or ordering | Cache rewrite after the same tools were sent in a different order | $0.00 |
| A38 | Thinking or effort changes invalidating cached context | Cache rewrite right after `/effort` | $0.00 |
| A40 | Cache isolation across providers or workspaces | Cache rewrite after an organization switch (provider switches aren't recorded) | $0.00 |
| A68 | Large invoked skill bodies | Skill bodies above 3k tokens, beyond 1.5k charged until compaction | $0.06 |
| A70 | Verbose plugin or hook context injection | MCP server instructions and hook context above 300 tokens per block | $0.42 |
| A104 | Duplicate sources containing the same information | A web result 50%+ the same (8-word shingles) as one from another URL or query | $0.00 |
| A116 | PDF page-image processing alongside extracted text | The same PDF read as page images and through a text extractor; the later read is charged | $0.00 |
| A117 | Duplicate OCR and document-text inputs | The same document read as images and through OCR | $0.00 |
| A138 | Scheduled tasks repeating unchanged analysis | A first request matching an earlier session exactly, with 80%+ of tool results unchanged | $0.00 |

A $0.00 result means nothing was found in this data, not that the detector is broken. A synthetic session triggered every new detector except A19 and A27, which it had no input for.

A25, A26, A27, A29, A38 and A40 put a name on cache rewrites that #3 used to report only as "context changed". The same cost still counts in #3.

## Curated (50-category) changes

| # | Change |
|---|---|
| 46 | Renamed "Tool discovery and skill loading"; adds A68 |
| 33 | Large images and PDFs: adds A116 and A117 |
| 37 | Web pages and search results: adds A104 |
| 48, 49 | Now measured |

The other new rows only split up the cost of #1 or #3, so adding them to a curated row would count that cost twice. They appear in `--all` only.

## Still unmeasurable

| Why | Rows | Possible route |
|---|---|---|
| Needs a judgement of what was relevant or necessary (17) | A3, A4, A20, A44, A46, A47, A48, A55, A56, A59, A102, A108, A113, A119, A129, A130, A132 | Opt-in LLM-judge pass over a sample of sessions, reported as estimates |
| Needs the exact request body: cache breakpoints, edited messages (4) | A28, A31, A32, A33 | Opt-in local logging proxy via `ANTHROPIC_BASE_URL` |
| Model calls that never reach transcripts (3) | A36, A137, A140 | Claude Code OpenTelemetry `api_request` events |
| Needs matched experiment runs (3) | A42, A49, A50 | Headless `claude -p` benchmark; `count_tokens` on both models for A50 |
| Settings that aren't recorded (2) | A39 (`tool_choice`), A43 (whether earlier thinking blocks are re-sent) | Logging proxy |
| Coverage gap, not a cost | #11 No visibility | Enable the hooks |
| Needs hook data | #10 Usage while idle | Enable the hooks |

The full row names are listed in `token-leak-categories.md`.

## Caveats

- #48 and #49 only cover sessions whose Claude Code version records prompt snapshots and skill listings (154 of 163 here).
- A18 checks whether memory files still exist when the report runs, not when the session ran.
- Tool definitions are sized at 4 characters per token, like every other item in the cost model.

## Files changed

- `plugins/token-metrics/scripts/leak_report.py`: attachment parsing, skill bodies, prefix-change events, #12, #13
- `plugins/token-metrics/scripts/leak_extra.py`: the A-row detectors and updated unmeasurable reasons
- `plugins/token-metrics/scripts/leak_categories.py`, `leaderboard/lib/categories.json`: curated rows 33, 37, 46
- `token-leak-categories.md`, `plugins/token-metrics/README.md`, `.claude-plugin/plugin.json` (1.4.0)
