#!/usr/bin/env python3
"""
analyze.py - turn hook events + Claude Code transcripts into one row per task,
then summarise by category.

  python3 analyze.py                      # reads ~/.claude/metrics/events.jsonl
  python3 analyze.py --since 2026-10-01 --csv tasks.csv

A task starts at a prompt tagged [category] (or at session start) and runs until the
next tagged prompt or the end of the session. Untagged prompts are follow-ups.
Tokens come from the transcript's per-message usage; cost is API list price
(for subscription users that is the API-equivalent cost, not what you pay).
"""
import argparse
import csv
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone

# in, out, cache read per MTok, by model version (Anthropic first-party list prices); same table as leak_report.py
PRICES = {
    "claude-fable-5-1": (10.00, 50.00, 0.25), "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20), "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50), "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50), "claude-opus-4-5": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20), "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30), "claude-sonnet-4-5": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
PRICE_IDS = sorted(PRICES, key=len, reverse=True)
FAMILY_PRICES = {"fable": PRICES["claude-fable-5-1"], "opus": PRICES["claude-opus-5-5"],
                 "sonnet": PRICES["claude-sonnet-5-5"], "haiku": PRICES["claude-haiku-4-5"]}
# cache-write price / input price by recorded cache lifetime; unrecorded writes use leak_report.py's default (1h)
WRITE_MULT = {"ephemeral_5m_input_tokens": 1.25, "ephemeral_1h_input_tokens": 2.0}
CACHE_WRITE_MULT = 2.0
SYNTHETIC = "<synthetic>"   # messages Claude Code writes itself: not model calls

FIELDS = ["session_id", "task_no", "category", "start", "prompts", "api_calls", "tool_calls",
          "models", "input", "cache_write", "cache_read", "output", "cost_usd", "cache_hit_rate",
          "first_response_s", "median_turn_s", "tool_s", "total_s", "corrections", "interrupts",
          "reverts", "compactions", "rating", "outcome"]


def iso(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def price_for(model):
    m = (model or "").lower()
    version = next((k for k in PRICE_IDS if k in m), None)
    if version:
        return PRICES[version]
    return next((p for k, p in FAMILY_PRICES.items() if k in m), FAMILY_PRICES["sonnet"])


def write_cost_mult(usage):
    total = usage.get("cache_creation_input_tokens", 0) or 0
    split = usage.get("cache_creation") or {}
    if not total or not isinstance(split, dict):
        return CACHE_WRITE_MULT
    known = {k: split.get(k, 0) or 0 for k in WRITE_MULT}
    rest = max(0, total - sum(known.values()))
    return (sum(n * WRITE_MULT[k] for k, n in known.items()) + rest * CACHE_WRITE_MULT) / total


def read_transcript(path):
    """Assistant messages (deduplicated by id) and user-interrupt markers, with timestamps."""
    msgs, interrupts, seen = [], [], set()
    if not path or not os.path.exists(path):
        return msgs, interrupts
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            ts = e.get("timestamp")
            if not ts:
                continue
            msg = e.get("message") or {}
            if e.get("type") == "assistant" and msg.get("usage") and msg.get("model") != SYNTHETIC:
                mid = msg.get("id") or e.get("uuid")
                if mid in seen:
                    continue
                seen.add(mid)
                u = msg["usage"]
                msgs.append({"t": iso(ts), "model": msg.get("model", ""),
                             "input": u.get("input_tokens", 0) or 0,
                             "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
                             "cache_read": u.get("cache_read_input_tokens", 0) or 0,
                             "output": u.get("output_tokens", 0) or 0,
                             "write_mult": write_cost_mult(u)})
            elif e.get("type") == "user" and "interrupted by user" in json.dumps(msg.get("content", "")):
                interrupts.append(iso(ts))
    return msgs, interrupts


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def build_tasks(events, since):
    by_session = defaultdict(list)
    for e in events:
        if e.get("session_id") and e["ts"] >= since:
            by_session[e["session_id"]].append(e)
    rows = []
    for sid, evs in by_session.items():
        evs.sort(key=lambda e: e["ts"])
        path = next((e["transcript_path"] for e in reversed(evs) if e.get("transcript_path")), None)
        msgs, transcript_interrupts = read_transcript(path)
        prompts = [e for e in evs if e["event"] == "UserPromptSubmit" and e.get("kind") == "prompt"]
        if not prompts:
            continue
        starts = [p for i, p in enumerate(prompts) if i == 0 or p.get("category")]
        session_end = max([e["ts"] for e in evs] + [m["t"] for m in msgs]) + 1
        for n, start in enumerate(starts):
            t0 = start["ts"]
            t1 = starts[n + 1]["ts"] if n + 1 < len(starts) else session_end
            inside = [e for e in evs if t0 <= e["ts"] < t1]
            mm = [m for m in msgs if t0 <= m["t"] < t1]
            task_prompts = [e for e in inside if e["event"] == "UserPromptSubmit" and e.get("kind") == "prompt"]
            stops = [e for e in inside if e["event"] == "Stop"]

            turn_s = []
            for p in task_prompts:
                nxt = next((s["ts"] for s in stops if s["ts"] > p["ts"]), None)
                if nxt:
                    turn_s.append(nxt - p["ts"])
            first = next((m["t"] for m in mm if m["t"] > t0), None)

            pre = {e["tool_use_id"]: e["ts"] for e in inside if e["event"] == "PreToolUse" and e.get("tool_use_id")}
            tool_s = sum(e["ts"] - pre[e["tool_use_id"]] for e in inside
                         if e["event"] in ("PostToolUse", "PostToolUseFailure") and e.get("tool_use_id") in pre)

            tok = {k: sum(m[k] for m in mm) for k in ("input", "cache_write", "cache_read", "output")}
            cost = 0.0
            for m in mm:
                pi, po, pr = price_for(m["model"])
                cost += (m["input"] * pi + m["cache_write"] * pi * m["write_mult"]
                         + m["cache_read"] * pr + m["output"] * po) / 1e6
            seen_in = tok["input"] + tok["cache_write"] + tok["cache_read"]
            ratings = [e for e in inside if e.get("kind") == "rating"]
            last_activity = max([e["ts"] for e in inside if e.get("kind") != "rating"] + [t0])

            rows.append({
                "session_id": sid[:8], "task_no": n + 1, "category": start.get("category") or "untagged",
                "start": datetime.fromtimestamp(t0, timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "prompts": len(task_prompts), "api_calls": len(mm),
                "tool_calls": sum(1 for e in inside if e["event"] == "PreToolUse"),
                "models": "+".join(sorted({m["model"] for m in mm if m["model"]})),
                **tok, "cost_usd": round(cost, 4),
                "cache_hit_rate": round(tok["cache_read"] / seen_in, 3) if seen_in else None,
                "first_response_s": round(first - t0, 1) if first else None,
                "median_turn_s": round(statistics.median(turn_s), 1) if turn_s else None,
                "tool_s": round(tool_s, 1), "total_s": round(last_activity - t0, 1),
                "corrections": sum(1 for p in task_prompts if p.get("correction")),
                "interrupts": sum(1 for t in transcript_interrupts if t0 <= t < t1)
                              + sum(1 for e in inside if e.get("is_interrupt")),
                "reverts": sum(1 for e in inside if e["event"] == "PreToolUse" and e.get("git_revert")),
                "compactions": sum(1 for e in inside if e["event"] == "PreCompact"),
                "rating": ratings[-1]["rating"] if ratings else None,
                "outcome": ratings[-1].get("outcome") if ratings else None,
            })
    return rows


def summarise(rows):
    cats = defaultdict(list)
    for r in rows:
        cats[r["category"]].append(r)
    head = f"{'category':<12}{'tasks':>6}{'success':>9}{'tokens p50':>12}{'cost p50':>10}{'cost/succ':>11}" \
           f"{'turn s p50':>11}{'p90':>7}{'corr/task':>10}{'intr/task':>10}{'rating':>8}"
    print(head)
    print("-" * len(head))
    for cat, rs in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        rated = [r for r in rs if r["outcome"]]
        ok = [r for r in rated if r["outcome"] == "ok"]
        succ = f"{len(ok) / len(rated):.0%}" if rated else "-"
        tokens = [r["input"] + r["cache_write"] + r["cache_read"] + r["output"] for r in rs]
        turns = [r["median_turn_s"] for r in rs if r["median_turn_s"] is not None]
        per_success = f"${sum(r['cost_usd'] for r in rated) / len(ok):.2f}" if ok else "-"
        ratings = [r["rating"] for r in rs if r["rating"]]
        print(f"{cat:<12}{len(rs):>6}{succ:>9}{pct(tokens, .5) or 0:>12,}"
              f"{'$%.2f' % pct([r['cost_usd'] for r in rs], .5):>10}{per_success:>11}"
              f"{pct(turns, .5) or '-':>11}{pct(turns, .9) or '-':>7}"
              f"{sum(r['corrections'] for r in rs) / len(rs):>10.2f}"
              f"{sum(r['interrupts'] for r in rs) / len(rs):>10.2f}"
              f"{(sum(ratings) / len(ratings)) if ratings else 0:>8.1f}")
    print("\nsuccess and cost/succ use only tasks rated with an outcome; rating is mean frustration (1 smooth - 5 bad)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=os.path.expanduser("~/.claude/metrics/events.jsonl"))
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--csv", help="write one row per task to this file")
    a = ap.parse_args()
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp() if a.since else 0
    if not os.path.exists(a.events):
        print(f"No task data yet ({a.events} not found). Start a session and tag a task, e.g. [bugfix] ...")
        return
    with open(a.events) as f:
        events = [json.loads(l) for l in f if l.strip()]
    rows = build_tasks(events, since)
    if not rows:
        print("no tasks found")
        return
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} tasks to {a.csv}\n")
    summarise(rows)


if __name__ == "__main__":
    main()
