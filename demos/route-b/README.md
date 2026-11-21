# Route B demo: Claude hands small tasks to Antigravity

Claude Code stays the lead. For a small task it calls the `antigravity` MCP server, which runs the
Antigravity CLI (`agy`) headless on a Gemini model in a throwaway git worktree. Claude reviews the diff and
merges or discards it.

```
Developer ──▶ Claude Code (lead: plans, reviews)
                 │ delegate_task(task, acceptance_checks, check_command)
                 ▼
            antigravity_mcp.py ──▶ git worktree ──▶ agy -p … --model gemini-3.8-flash-medium
                 │                                   └▶ check_command (tests)
                 ◀── summary · check result · diff · Gemini token usage
                 │ merge_delegation(id) / discard_delegation(id)
                 ▼
            real working tree            + one line per task in ~/.claude/metrics/delegations.jsonl
```

## Files

| File | What it does |
| --- | --- |
| `antigravity_mcp.py` | MCP server (stdio, standard library only): `delegate_task`, `merge_delegation`, `discard_delegation` |
| `setup_demo.sh` | Builds a sample repo with 4 failing tests and Claude Code wired to the server |
| `report.py` | Table of every delegation: time, tokens on Gemini, checks, diff size, merged or not |

## Before the call

- `agy` installed and signed in (`agy models` lists Gemini models).
- `./setup_demo.sh` (creates `~/route-b-demo`; pass another path to change it).
- Do one dry run: the first `agy` call takes a minute.

## Run of show (about 5 minutes)

1. `cd ~/route-b-demo && python3 -m unittest -q`: 4 failing tests (a slugify bug, a missing `parse_duration`).
2. Show `CLAUDE.md`: the routing rule that says which tasks go to Antigravity.
3. `claude`, then: **"Fix the failing tests."**
   Claude sees two small, independent tasks and calls `delegate_task` twice. Each returns Gemini's diff,
   the passing check and the tokens Gemini used.
4. Claude reviews each diff, calls `merge_delegation`, then runs the tests in the real tree: all pass.
5. `python3 <this dir>/report.py`: the Gemini tokens per task, which Claude Code's own transcripts never
   show. Add `--price-in X --price-out Y` (USD per million tokens, current Gemini list prices) for cost.

## Talking points

- The developer never leaves Claude Code; Antigravity works in an isolated worktree, so nothing lands
  without Claude's review.
- The routing rule is plain text in `CLAUDE.md`, so each team can tune which task types go over.
- The delegation log is how Report 2A counts Gemini spend; without it the work would look free.

## Limits (demo, not product)

- The worktree starts from `HEAD`: uncommitted changes are not visible to Antigravity.
- `agy` runs with `--dangerously-skip-permissions` inside the worktree. Fine for a demo; a customer setup
  should use `--sandbox` or an allow-list.
- `agy` sometimes reports `status: ERROR` after finishing, from background telemetry calls. The server
  judges a delegation by the exit code and the check command instead, and keeps `agy_status` for reference.
- No "compare with Claude" switch yet: that would run Claude on the same task in a second worktree.
