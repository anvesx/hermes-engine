# Top 5 category guide

How each of the five detectors works.

## First, the shared building blocks

All five use numbers the parser (`class Session` in `leak_report.py`) pulls out of each model call's `usage` block in the transcript (`leak_report.py:449-461`):

| Name in code | Meaning |
|---|---|
| `in` | input tokens sent uncached |
| `cw` | tokens **written** to the cache on this call |
| `cr` | tokens **read** from the cache on this call |
| `out` | output tokens Claude generated |
| `ctx` | `in + cw + cr`, the whole conversation size sent on this call |
| `cost` | `in × input price + cw × input price × write multiplier + cr × cache-read price + out × output price` |
| `read_price` | cache-read price of one token |

The examples below use Opus 4.7 list prices from the `PRICES` table: input $5, output $25 and cache read $0.50 per million tokens.

One helper comes up a lot. **`carry(time, tokens)`** answers: "if these tokens sit in the conversation from this moment on, what does re-reading them cost?" It multiplies the tokens by the cache-read price of every later call, and stops at the next compaction (or at a given end time).

---

## 1. Heavy starting context (core leak #1)

**Where:** `leak_report.py:579-583`

**Idea:** before you type anything, every call already carries CLAUDE.md, tool definitions, MCP schemas, memory and skills. Everything above a "reasonable" 10,000 tokens is charged on **every** call in the session.

**How it's computed:**

1. Take the context size of the session's first call.
2. Subtract the size of your first prompt. What's left is pure setup (`prefix`).
3. If `prefix > 10,000` (`START_BASELINE`), then `extra = prefix − 10,000`.
4. Cost = `extra × (sum of cache-read prices of all calls in the session)`.

```python
prefix = s.start_ctx - s.start_prompt
if prefix > START_BASELINE:
    extra = prefix - START_BASELINE
    add(1, extra * s.prefix_read[-1], ...)   # prefix_read[-1] = sum of read prices of all calls
```

**Example:** first call context 25,000 and first prompt 500, so the prefix is 24,500 and the extra is 14,500. Over 60 calls:
14,500 × 60 = 870,000 tokens × $0.50/M = **$0.44** for that session.

---

## 2. Sessions that never end (core leak #2)

**Where:** `leak_report.py:585-592`, plus `tasks()` at `leak_report.py:539`

**Idea:** you finish one task and start an unrelated one in the same chat. The new task drags along all the old history, and you pay to re-read it on every call of the new task.

**How it's computed:**

1. **Split the session into tasks.** A new task starts when either:
   - your prompt starts with a tag like `[bugfix]`, or
   - you send a prompt after 30+ minutes idle (`TASK_GAP_S`).
2. For every task after the first:

   ```
   carried = first call's context − starting setup − this task's prompt
   ```

   That's the old history the new task inherited.
3. If `carried > 20,000` (`CARRY_MIN`), cost = `carry(task start, carried, until task end)`, i.e. carried tokens × the read price of each call in that task. It stops early if a compaction happens.

**Example:** task 2's first call has 94,500 context, the setup is 24,500 and the prompt is 1,000, so 69,000 tokens were carried over. Task 2 runs 30 calls:
69,000 × 30 = 2.07M tokens × $0.50/M = **$1.04**

---

## 3. Long history replay (canvas row A1, `lid(1)`)

**Where:** `leak_extra.py:257-262`

**Idea:** this one ignores tasks. It just asks, on every single call: "is the conversation history bigger than 100,000 tokens?" Each call pays for the part above that limit.

**How it's computed:**

For each main call:

```
over = ctx − starting context − 100,000      (HISTORY_LIMIT)
```

If `over > 0`, add `over × read_price`. The row total is the sum over all calls.

```python
over = [(c, c["ctx"] - first_ctx - HISTORY_LIMIT) for c in calls]
over = [(c, x) for c, x in over if x > 0]
add(lid(1), sum(x * c["read_price"] for c, x in over), ...)
```

**Example:** starting context is 25,000. Forty calls average 160,000 context, so each is 35,000 over the limit:
40 × 35,000 = 1.4M tokens × $0.50/M = **$0.70**

**#2 vs this one:** #2 measures *leftovers from an earlier task*, once per task. This one measures *raw length*, on every call, even if it's all one task. A long multi-task session can show up in **both** rows, so the same tokens can be counted twice across these two rows. Both rows are marked "spend to review".

---

## 4. Cache-write premium (canvas row A37, `lid(37)`)

**Where:** `leak_extra.py:288-314`, and `write_mult()` at `leak_report.py:182`

**Idea:** writing tokens into the cache costs **more** than sending them as normal input:

- 1.25× the input price for 5-minute caching
- 2× the input price for 1-hour caching

This row is the *extra* you paid on top of the normal input price.

**How it's computed:**

1. **Find the write multiplier** (`write_mult`). Newer transcripts split `cache_creation` into `ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`. The script takes a weighted average (all 1h gives 2.0, all 5m gives 1.25, a mix lands in between). Older entries without that split use `--ttl`: 2.0 by default, or 1.25 with `--ttl 5m`.
2. For every call, in the main thread **and** every helper agent:

   ```
   premium += cw × input price × (multiplier − 1)
   ```

```python
premium += c["cw"] * pi * (c["wmult"] - 1) / 1e6
```

**Example:** one call writes 40,000 tokens with 1-hour caching:
40,000 × $5/M × (2 − 1) = **$0.20**. With 5-minute caching it would be 40,000 × $5/M × 0.25 = $0.05.

**Note:** this is the price of caching itself, and later cheap reads usually pay it back. That's why the row is marked "spend to review, not all waste". It gets big when the cache is rewritten often: breaks, model switches, compactions, changed tool definitions. Those causes are broken out in their own rows.

---

## 5. Many agents (core leak #4)

**Where:** `leak_report.py:621-623`, using `load_sessions` at `leak_report.py:262`

**Idea:** sub-agents (the Agent/Task tool) each run their own conversation, and each one pays its own setup and reading costs. This row shows how much of your spend went to them.

**How it's computed:**

1. **Spot agent calls while loading.** A transcript entry counts as a helper if either:
   - it has `isSidechain: true`, or
   - it comes from a file in a `subagents` folder or named `agent-*.jsonl`.

   Those calls go into `helper_calls`, grouped by agent.
2. Cost = the **full** cost of every helper call added up (`helper_cost`), not just a wasted portion.
3. The detail line shows the agents' share of the session's total cost.

```python
if s.helper_calls:
    add(4, s.helper_cost, f"{len(s.helper_calls)} helper calls, {share:.0%} of session cost")
```

**Example:** the main thread costs $3.00 and three agents together cost $2.00. The row shows **$2.00**, "40% of session cost".

**Note:** this is the bluntest of the five because agents are often worth it. It's marked "review". The actual waste inside agent use is measured in separate rows:

- *Fork context duplication* (#4a): agents starting with 50,000+ tokens of inherited context
- *Overlapping agents* (#4b): two agents reading the same file
- *Verbose agent reports* (#4c)

---

## Summary

| Category | What it multiplies | Threshold | Counted for review only? |
|---|---|---|---|
| Heavy starting context | setup tokens above baseline × every call | 10,000 | no |
| Sessions that never end | old-task tokens × calls in the new task | 20,000 | no |
| Long history replay | history above limit, on each call | 100,000 | yes |
| Cache-write premium | cache-write tokens × (multiplier − 1) × input price | none | yes |
| Many agents | full cost of all helper-agent calls | none | yes |

The thresholds are constants at the top of the files (`leak_report.py:74-85`, `leak_extra.py:22`). Changing one changes what counts as a leak.
