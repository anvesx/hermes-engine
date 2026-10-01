#!/usr/bin/env python3
"""
leak_report.py - rank the 11 token-leak problems by estimated cost, from Claude Code transcripts.

Works on existing history: Claude Code already saves every session as JSONL under
~/.claude/projects/, so no setup is needed for 10 of the 11 leaks. The hook events from
metrics_hook.py (optional) add idle-usage detection and frustration ratings.

  python3 leak_report.py                       # all sessions
  python3 leak_report.py --since 2026-09-01 --md leak_report.md
  python3 leak_report.py --ttl 5m              # API-key users (5-minute cache)

How "cost" is estimated
  Token counts per model call come from the transcript (exact). The size of individual items
  (a tool result, a prompt) is estimated at 4 characters per token. A leaked item is charged
  for every later call that re-reads it, at the cache-read price, until the next compaction.
  All prices are API list prices: for subscription users this is API-equivalent usage,
  which is what drains the plan's allowance.
"""
import argparse
import bisect
import glob
import hashlib
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone

# ------------------------------------------------------------------ settings

PRICES = {"fable": (10.00, 50.00, 0.25), "opus": (4.00, 20.00, 0.20),
          "sonnet": (2.00, 10.00, 0.20), "haiku": (1.00, 5.00, 0.10)}   # in, out, cache read per MTok
CHARS_PER_TOKEN = 4
START_BASELINE = 10_000        # starting context considered reasonable
CARRY_MIN = 20_000             # history carried into a new task before it counts as a leak
TASK_GAP_S = 30 * 60           # an untagged prompt after this much idle time starts a new task
EXPLORE_LIMIT = 15             # reads/searches before the first edit considered reasonable
BIG_RESULT = 4_000             # tool result size that counts as oversized
BIG_KEEP = 2_000               # portion of an oversized result that is charged as useful
SIMPLE_CATEGORIES = {"docs", "explain", "question", "rename", "chore", "commit"}
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
DEP_DIRS = re.compile(r"(^|/)(node_modules|\.venv|venv|dist|build|target|\.next|vendor|__pycache__)/")
ERROR_TEXT = re.compile(r"(error|failed|traceback|exception|exit code [1-9]|not found)", re.I)
TAG_RE = re.compile(r"^\s*\[([A-Za-z][\w-]*)\]")

LEAKS = {
    1: "Sessions that never end", 2: "Heavy starting context", 3: "No clear direction",
    4: "Too much tool output", 5: "Bigger model than needed", 6: "Losing the cache",
    7: "Many agents", 8: "Retry loops", 9: "Usage while idle", 10: "Wordy responses",
    11: "No visibility",
}
SPEND_NOT_WASTE = {7}   # reported as spend to review, not counted as pure waste


def tok(chars):
    return chars // CHARS_PER_TOKEN


def price(model):
    m = (model or "").lower()
    return next((p for k, p in PRICES.items() if k in m), PRICES["sonnet"])


def ts_of(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(c.get("text", "")) if isinstance(c, dict) else len(str(c)) for c in content)
    return len(json.dumps(content)) if content else 0


def text_of(content, limit=4000):
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))[:limit]
    return ""

# ------------------------------------------------------------------ loading


def load_sessions(root, since):
    """Group transcript entries by session; mark helper-agent entries."""
    sessions = defaultdict(list)
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        helper_file = "subagent" in path.lower() or os.path.basename(path).startswith("agent-")
        project = os.path.relpath(path, root).split(os.sep)[0]
        try:
            with open(path, errors="replace") as f:
                for n, line in enumerate(f):
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    t = ts_of(e.get("timestamp", "")) if e.get("timestamp") else None
                    if t is None or t < since:
                        continue
                    sid = e.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
                    e["_t"], e["_n"], e["_project"] = t, n, project
                    e["_helper"] = bool(e.get("isSidechain")) or helper_file
                    sessions[sid].append(e)
        except OSError:
            continue
    for evs in sessions.values():
        evs.sort(key=lambda e: (e["_t"], e["_n"]))
    return sessions


def load_hook_prompts(path):
    prompts = defaultdict(list)
    ratings = defaultdict(list)
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event") == "UserPromptSubmit":
                    (ratings if e.get("kind") == "rating" else prompts)[e.get("session_id")].append(e)
    return prompts, ratings

# ------------------------------------------------------------------ per-session analysis


class Session:
    def __init__(self, sid, entries, write_mult, ttl_s, hook_prompts):
        self.sid, self.project = sid, entries[0]["_project"]
        self.write_mult, self.ttl_s = write_mult, ttl_s
        self.hook_prompts = hook_prompts
        self.calls, self.helper_calls = [], []      # assistant model calls
        self.prompts, self.tool_uses, self.results = [], {}, []
        self.compactions = []
        self._parse(entries)
        self._segments()

    # -- parsing ---------------------------------------------------------------
    def _parse(self, entries):
        by_id = {}
        for e in entries:
            msg = e.get("message") or {}
            content = msg.get("content")
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary" or e.get("isCompactSummary"):
                if not e["_helper"]:
                    self.compactions.append(e["_t"])
                continue
            if e.get("type") == "assistant" and msg.get("usage"):
                mid = msg.get("id") or e.get("uuid")
                c = by_id.get(mid)
                if c is None:
                    c = {"t": e["_t"], "model": msg.get("model", ""), "blocks": [], "helper": e["_helper"]}
                    by_id[mid] = c
                    (self.helper_calls if e["_helper"] else self.calls).append(c)
                c["usage"] = msg["usage"]
                if isinstance(content, list):
                    c["blocks"].extend(b for b in content if isinstance(b, dict))
            elif e.get("type") == "user" and not e["_helper"]:
                if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            txt = text_of(b.get("content"))
                            self.results.append({"t": e["_t"], "id": b.get("tool_use_id"),
                                                 "tokens": tok(text_len(b.get("content"))),
                                                 "error": bool(b.get("is_error")) or bool(ERROR_TEXT.search(txt[:600])),
                                                 "text": txt})
                elif not e.get("isMeta"):
                    txt = text_of(content)
                    if txt and "interrupted by user" not in txt:
                        self.prompts.append({"t": e["_t"], "tokens": tok(len(txt)), "text": txt})

        for c in self.calls + self.helper_calls:
            u = c["usage"]
            c["in"] = u.get("input_tokens", 0) or 0
            c["cw"] = u.get("cache_creation_input_tokens", 0) or 0
            c["cr"] = u.get("cache_read_input_tokens", 0) or 0
            c["out"] = u.get("output_tokens", 0) or 0
            c["ctx"] = c["in"] + c["cw"] + c["cr"]
            pi, po, pr = price(c["model"])
            c["cost"] = (c["in"] * pi + c["cw"] * pi * self.write_mult + c["cr"] * pr + c["out"] * po) / 1e6
            c["read_price"] = pr / 1e6
            if c["helper"]:
                continue   # helper agents' tool calls are not part of the main context
            for b in c["blocks"]:
                if b.get("type") == "tool_use":
                    self.tool_uses[b.get("id")] = {"t": c["t"], "name": b.get("name"),
                                                  "input": b.get("input") or {}, "call": c}
        for r in self.results:
            tu = self.tool_uses.get(r["id"])
            r["name"] = tu["name"] if tu else None
            r["input"] = tu["input"] if tu else {}
            r["call"] = tu["call"] if tu else None
        self.cost = sum(c["cost"] for c in self.calls)
        self.helper_cost = sum(c["cost"] for c in self.helper_calls)

    def _segments(self):
        """Calls between compactions; used to charge re-reads only until the next compaction."""
        self.call_times = [c["t"] for c in self.calls]
        self.prefix_read = [0.0]
        for c in self.calls:
            self.prefix_read.append(self.prefix_read[-1] + c["read_price"])
        self.comp_sorted = sorted(self.compactions)

    def carry(self, t, tokens, until=None):
        """Cost of re-reading `tokens` on every main call after time t, until compaction or `until`."""
        if tokens <= 0:
            return 0.0
        i = bisect.bisect_right(self.call_times, t)
        k = bisect.bisect_right(self.comp_sorted, t)
        end_t = self.comp_sorted[k] if k < len(self.comp_sorted) else float("inf")
        if until is not None:
            end_t = min(end_t, until)
        j = bisect.bisect_left(self.call_times, end_t)
        return tokens * (self.prefix_read[j] - self.prefix_read[i]) if j > i else 0.0

    # -- tasks -------------------------------------------------------------------
    def tasks(self):
        out = []
        for n, p in enumerate(self.prompts):
            tag = TAG_RE.match(p["text"])
            i = bisect.bisect_left(self.call_times, p["t"])
            last_activity = self.call_times[i - 1] if i > 0 else (self.prompts[n - 1]["t"] if n else None)
            gap = last_activity is not None and p["t"] - last_activity >= TASK_GAP_S
            if not out or tag or gap:
                out.append({"start": p["t"], "category": tag.group(1).lower() if tag else None,
                            "prompt_tokens": p["tokens"], "by": "tag" if tag else ("gap" if gap else "start")})
        for n, tsk in enumerate(out):
            tsk["end"] = out[n + 1]["start"] if n + 1 < len(out) else float("inf")
            tsk["calls"] = [c for c in self.calls if tsk["start"] <= c["t"] < tsk["end"]]
        return out


# ------------------------------------------------------------------ leak detectors


def analyse(s: Session, findings):
    if not s.calls:
        return
    tasks = s.tasks()
    first = s.calls[0]
    first_prompt = s.prompts[0]["tokens"] if s.prompts else 0
    prefix = max(0, first["ctx"] - first_prompt)

    def add(leak, cost, detail):
        findings[leak].append({"cost": cost, "session": s.sid[:8], "project": s.project, "detail": detail})

    # 2. Heavy starting context: excess over the baseline, re-read on every call
    findings["_prefix_sizes"].append(prefix)
    if prefix > START_BASELINE:
        extra = prefix - START_BASELINE
        add(2, extra * s.prefix_read[-1], f"starting context ~{prefix:,} tokens over {len(s.calls)} calls")

    # 1. Sessions that never end: history carried from earlier tasks into later ones
    for tsk in tasks[1:]:
        if not tsk["calls"]:
            continue
        carried = tsk["calls"][0]["ctx"] - prefix - tsk["prompt_tokens"]
        if carried > CARRY_MIN:
            add(1, s.carry(tsk["start"], carried, until=tsk["end"]),
                f"new task ({tsk['category'] or 'after ' + str(TASK_GAP_S // 60) + ' min gap'}) carried ~{carried:,} old tokens")
    if len(s.compactions):
        findings["_compactions"].append(len(s.compactions))

    # 3. No clear direction: exploration calls before the first edit, beyond the limit
    for tsk in tasks:
        uses = sorted([u for u in s.tool_uses.values() if tsk["start"] <= u["t"] < tsk["end"]], key=lambda u: u["t"])
        first_edit = next((u["t"] for u in uses if u["name"] in EDIT_TOOLS), None)
        if first_edit is None:
            continue
        explore = [u for u in uses if u["t"] < first_edit]
        if len(explore) > EXPLORE_LIMIT:
            calls = {id(u["call"]): u["call"] for u in explore[EXPLORE_LIMIT:]}
            add(3, sum(c["cost"] for c in calls.values()),
                f"{len(explore)} reads/searches before the first edit")

    # 4. Too much tool output: duplicate reads, dependency-folder hits, oversized results
    seen_reads, edited_since = {}, set()
    for r in sorted(s.results, key=lambda r: r["t"]):
        name, inp = r["name"], r["input"]
        path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
        if name in EDIT_TOOLS and path:
            edited_since.add(path)
        if name == "Read" and path:
            key = (path, inp.get("offset"), inp.get("limit"))
            if key in seen_reads and path not in edited_since:
                add(4, s.carry(r["t"], r["tokens"]), f"re-read {os.path.basename(path)} (~{r['tokens']:,} tokens)")
                continue
            seen_reads[key] = r["t"]
            edited_since.discard(path)
        dep_lines = [l for l in r["text"].splitlines() if DEP_DIRS.search(l)]
        if name in ("Grep", "Glob", "Bash", "LS") and len(dep_lines) >= 5:
            dep_tokens = int(r["tokens"] * len(dep_lines) / max(1, len(r["text"].splitlines())))
            add(4, s.carry(r["t"], dep_tokens), f"{name} returned results from dependency/build folders ({len(dep_lines)}+ lines)")
        elif r["tokens"] > BIG_RESULT:
            what = os.path.basename(path) if path else (str(inp.get("command", ""))[:40] or name)
            add(4, s.carry(r["t"], r["tokens"] - BIG_KEEP), f"{name} result ~{r['tokens']:,} tokens ({what})")

    # 5. Bigger model than needed: premium models on simple categories, and premium helpers
    for tsk in tasks:
        if tsk["category"] in SIMPLE_CATEGORIES:
            for c in tsk["calls"]:
                m = c["model"].lower()
                if "opus" in m or "fable" in m:
                    pi, po, pr = PRICES["sonnet"]
                    cheaper = (c["in"] * pi + c["cw"] * pi * s.write_mult + c["cr"] * pr + c["out"] * po) / 1e6
                    add(5, c["cost"] - cheaper, f"[{tsk['category']}] task on {c['model']}")
    for c in s.helper_calls:
        m = c["model"].lower()
        if "opus" in m or "fable" in m:
            pi, po, pr = PRICES["sonnet"]
            cheaper = (c["in"] * pi + c["cw"] * pi * s.write_mult + c["cr"] * pr + c["out"] * po) / 1e6
            add(5, c["cost"] - cheaper, f"helper agent on {c['model']}")
    for c in s.calls:
        think = sum(len(b.get("thinking", "")) for b in c["blocks"] if b.get("type") == "thinking")
        findings["_thinking"].append(tok(think))

    # 6. Losing the cache: large rewrites after the first call, with likely cause
    comp = s.comp_sorted
    for i in range(1, len(s.calls)):
        c, prev = s.calls[i], s.calls[i - 1]
        if c["cw"] > max(5_000, 0.5 * c["ctx"]):
            gap = c["t"] - prev["t"]
            if any(prev["t"] < x <= c["t"] for x in comp):
                cause = "after compaction"
            elif c["model"] != prev["model"]:
                cause = "model switch"
            elif gap >= 3600:
                cause = f"break of {gap / 60:.0f} min"
            elif gap >= s.ttl_s:
                cause = f"break of {gap / 60:.0f} min (past cache lifetime)"
            else:
                cause = "context changed (tools, instructions, settings)"
            pi, _, pr = price(c["model"])
            add(6, c["cw"] * (pi * s.write_mult - pr) / 1e6, f"~{c['cw']:,} tokens rewritten, {cause}")

    # 7. Many agents: helper spend (to review, not all waste)
    if s.helper_calls:
        add(7, s.helper_cost, f"{len(s.helper_calls)} helper calls, {s.helper_cost / max(1e-9, s.cost + s.helper_cost):.0%} of session cost")

    # 8. Retry loops: the same failing tool call repeated; charge attempts after the second
    attempts = defaultdict(int)
    for r in sorted(s.results, key=lambda r: r["t"]):
        if not r["call"]:
            continue
        key = (r["name"], hashlib.md5(json.dumps(r["input"], sort_keys=True).encode()).hexdigest())
        if r["error"]:
            attempts[key] += 1
            if attempts[key] >= 3:
                add(8, r["call"]["cost"], f"{r['name']} failed {attempts[key]} times with the same input")
        else:
            attempts[key] = 0

    # 9. Usage while idle: prompts not typed by the developer (needs hook data)
    hp = s.hook_prompts.get(s.sid)
    if hp is not None:
        typed = [e["ts"] for e in hp]
        for n, p in enumerate(s.prompts):
            if not any(abs(p["t"] - t) < 15 for t in typed):
                end = s.prompts[n + 1]["t"] if n + 1 < len(s.prompts) else float("inf")
                cost = sum(c["cost"] for c in s.calls if p["t"] <= c["t"] < end)
                if cost:
                    add(9, cost, "turn started without a typed prompt (scheduled task, loop or background message)")
        findings["_hook_sessions"].append(s.sid)

    # 10. Wordy responses: output share and whole-file rewrites of existing files
    findings["_output_cost"].append(sum(c["out"] * price(c["model"])[1] / 1e6 for c in s.calls))
    read_paths = set()
    for u in sorted(s.tool_uses.values(), key=lambda u: u["t"]):
        path = u["input"].get("file_path", "")
        if u["name"] in ("Read", "Edit", "MultiEdit"):
            read_paths.add(path)
        elif u["name"] == "Write" and path in read_paths:
            out_tokens = tok(len(u["input"].get("content", "")))
            add(10, out_tokens * price(u["call"]["model"])[1] / 1e6,
                f"rewrote whole file {os.path.basename(path)} (~{out_tokens:,} tokens)")

    findings["_sessions"].append(s)

# ------------------------------------------------------------------ report


def report(findings, md_path=None, top=3):
    sessions = findings["_sessions"]
    total = sum(s.cost + s.helper_cost for s in sessions)
    lines = []
    w = lines.append
    days = sorted({datetime.fromtimestamp(c["t"], timezone.utc).date() for s in sessions for c in s.calls})
    w(f"# Token leak report\n")
    w(f"{len(sessions)} sessions, {days[0]} to {days[-1]}, API-equivalent spend ${total:,.2f}\n" if days else "no data\n")
    w("| # | Leak | Est. cost | Share of spend | Instances | Note |")
    w("|---|---|---|---|---|---|")
    rows = []
    for k, name in LEAKS.items():
        items = findings.get(k, [])
        cost = sum(i["cost"] for i in items)
        rows.append((k, name, cost, len(items)))
    for k, name, cost, n in sorted(rows, key=lambda r: -r[2]):
        note = ""
        if k in SPEND_NOT_WASTE:
            note = "spend to review, not all waste"
        elif k == 9 and not findings["_hook_sessions"]:
            note = "needs hook data"
        elif k == 11:
            have = len(set(findings["_hook_sessions"]))
            note = f"{have}/{len(sessions)} sessions have hook data (categories, ratings, idle detection)"
        elif k == 10:
            out = sum(findings["_output_cost"])
            note = f"all output is {out / total:.1%} of spend" if total else ""
        elif k == 2 and findings["_prefix_sizes"]:
            note = f"median starting context ~{int(statistics.median(findings['_prefix_sizes'])):,} tokens"
        elif k == 1 and findings["_compactions"]:
            note = f"{sum(findings['_compactions'])} compactions"
        elif k == 5 and findings["_thinking"]:
            visible = [t for t in findings["_thinking"] if t]
            note = f"median visible thinking ~{int(statistics.median(visible)):,} tokens/call" if visible else ""
        share = f"{cost / total:.1%}" if total else "-"
        w(f"| {k} | {name} | ${cost:,.2f} | {share} | {n} | {note} |")
    w("\nCosts overlap (a leaked tool result inside a never-ending session counts in both), so do not add them up.\n")
    for k, name, cost, n in sorted(rows, key=lambda r: -r[2]):
        items = sorted(findings.get(k, []), key=lambda i: -i["cost"])[:top]
        if items:
            w(f"\n## {k}. {name}: largest examples")
            for i in items:
                w(f"- ${i['cost']:.2f}  {i['project']} / session {i['session']}: {i['detail']}")
    text = "\n".join(lines)
    print(text)
    if md_path:
        with open(md_path, "w") as f:
            f.write(text + "\n")
        print(f"\nwrote {md_path}")


def main():
    ap = argparse.ArgumentParser(description="Rank Claude Code token leaks by estimated cost")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--events", default=os.path.expanduser("~/.claude/metrics/events.jsonl"))
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--days", type=int, help="only the last N days (instead of --since)")
    ap.add_argument("--ttl", choices=["5m", "1h"], default="1h",
                    help="cache lifetime: 1h on subscriptions, 5m on API keys or usage credits")
    ap.add_argument("--md", help="also write the report as Markdown")
    ap.add_argument("--top", type=int, default=3, help="examples shown per leak")
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp() if a.since else 0
    if a.days:
        since = datetime.now(timezone.utc).timestamp() - a.days * 86400
    ttl_s, write_mult = (300, 1.25) if a.ttl == "5m" else (3600, 2.0)
    hook_prompts, _ = load_hook_prompts(a.events)
    findings = defaultdict(list)
    for sid, entries in load_sessions(a.root, since).items():
        analyse(Session(sid, entries, write_mult, ttl_s, hook_prompts), findings)
    if not findings["_sessions"]:
        print(f"no sessions found under {a.root}")
        return
    report(findings, a.md, a.top)


if __name__ == "__main__":
    main()
