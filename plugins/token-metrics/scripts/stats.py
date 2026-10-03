#!/usr/bin/env python3
"""
stats.py - your Claude Code usage in numbers ("Wrapped"), and the aggregate payload share.py uploads.

  python3 stats.py                 # lifetime summary: tokens, spend, active hours, streaks, top leaks
  python3 stats.py --json          # the exact payload share.py would send (nothing is sent)
  python3 stats.py --weeks 4       # payload covers the last 4 weeks (default 8)

The payload holds aggregates only: per-week totals (tokens split into input / cache write / cache read / output,
by model family and main session vs subagents), per-day token totals for the last DAILY_DAYS days, and each
leak category's share of spend.
No prompt text, project names, file paths or session ids leave this machine.

Sessions are analysed once with leak_report.py's detectors, then each session (and its findings)
is assigned to the local ISO week of its first call. Weeks and days use local time, so streaks
match the user's calendar.
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import leak_categories
import leak_report

SCHEMA = 1
ACTIVE_GAP_S = 5 * 60          # a gap between calls/prompts longer than this counts as a break
PAYLOAD_WEEKS = 8
DAILY_DAYS = 56
SPLIT = (("input", "in"), ("cache_write", "cw"), ("cache_read", "cr"), ("output", "out"))
FAMILIES = ("fable", "opus", "sonnet", "haiku")


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), "other")


def week_of(t):
    y, w, _ = datetime.fromtimestamp(t).isocalendar()
    return f"{y}-W{w:02d}"


def day_of(t):
    return datetime.fromtimestamp(t).date().isoformat()


def collect(root, events):
    """Run the leak detectors over all history; returns (sessions, findings, hook ratings)."""
    hook_prompts, ratings = leak_report.load_hook_prompts(events)
    findings = defaultdict(list)
    for sid, entries in leak_report.load_sessions(root, 0).items():
        leak_report.analyse(leak_report.Session(sid, entries, 2.0, 3600, hook_prompts), findings)
    if findings["_sessions"]:
        leak_report.cross_session(findings)
    return findings["_sessions"], findings, ratings


def volume_by(s, key=week_of):
    """Tokens, cost, active time and days of one session, split by the week (or day) each call happened in,
    so a session left open for days doesn't pile everything onto its first week."""
    out = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "active_s": 0.0, "days": set(), "models": defaultdict(float),
                               "model_tokens": defaultdict(int), "split": Counter(), "agent_tokens": 0})
    calls = s.calls + s.helper_calls
    for c in calls:
        v = out[key(c["t"])]
        n = c["ctx"] + c["out"]
        v["tokens"] += n
        v["cost"] += c["cost"]
        v["models"][family(c["model"])] += c["cost"]
        v["model_tokens"][family(c["model"])] += n
        for name, f in SPLIT:
            v["split"][name] += c[f]
        if c["helper"]:
            v["agent_tokens"] += n
    times = sorted([c["t"] for c in calls] + [p["t"] for p in s.prompts])
    for a, b in zip(times, times[1:]):
        out[key(b)]["active_s"] += min(b - a, ACTIVE_GAP_S)
    for t in times:
        out[key(t)]["days"].add(day_of(t))
    return out


def session_stats(s, ratings, hook_sids):
    tasks = s.tasks()
    return {
        "volume": volume_by(s),
        "daily": volume_by(s, day_of),
        "tasks": len(tasks),
        "tagged": [t["category"] for t in tasks if t["by"] == "tag"],
        "rated": len(ratings.get(s.sid, [])),
        "hook": s.sid in hook_sids,
    }


def leak_shares(findings, sessions):
    """Share of spend per curated category, for the findings of these sessions only."""
    total = sum(s.cost + s.helper_cost for s in sessions)
    if not total:
        return {}, 0.0
    shares = {}
    for n, name, group, cost, items, reason, note in leak_report.curated_rows(findings, total, sessions):
        if reason is None:
            shares[str(n)] = round(cost / total, 4)
    # an index, not a percentage: categories overlap, so it can pass 1.0. Compared only to the user's own baseline.
    waste = sum(v for k, v in shares.items() if int(k) not in leak_categories.REVIEW)
    return shares, round(waste, 4)


def split_findings(findings, sessions):
    """findings restricted to the given sessions (findings record the session id's first 8 chars)."""
    keep = {s.sid[:8] for s in sessions}
    sids = {s.sid for s in sessions}
    out = defaultdict(list)
    for k, items in findings.items():
        if k == "_sessions":
            out[k] = list(sessions)
        elif k == "_hook_sessions":
            out[k] = [sid for sid in items if sid in sids]
        elif isinstance(k, int):
            out[k] = [i for i in items if i.get("session") in keep]
    return out


def longest_streak(days):
    best = run = 0
    prev = None
    for d in sorted(days):
        cur = datetime.fromisoformat(d).date()
        run = run + 1 if prev and cur - prev == timedelta(days=1) else 1
        best, prev = max(best, run), cur
    return best


def build(root, events, weeks=PAYLOAD_WEEKS):
    sessions, findings, ratings = collect(root, events)
    if not sessions:
        return None
    hook_sids = set(findings["_hook_sessions"])
    per = {s.sid: session_stats(s, ratings, hook_sids) for s in sessions}
    by_week = defaultdict(list)
    for s in sessions:
        by_week[week_of(s.calls[0]["t"])].append(s)

    def totals(ss, volume_week=None):
        """Counts come from sessions ss; volume from every session's activity in volume_week (None: all)."""
        st = [per[s.sid] for s in ss]
        vols = [v for x in per.values() for wk, v in x["volume"].items() if volume_week in (None, wk)]
        models, model_tokens, split = defaultdict(float), defaultdict(int), Counter()
        for v in vols:
            for f, c in v["models"].items():
                models[f] += c
            for f, n in v["model_tokens"].items():
                model_tokens[f] += n
            split.update(v["split"])
        cats = Counter(c for x in st for c in x["tagged"])
        days = set().union(*(v["days"] for v in vols))
        return {
            "tokens": sum(v["tokens"] for v in vols),
            "cost_usd": round(sum(v["cost"] for v in vols), 2),
            "active_hours": round(sum(v["active_s"] for v in vols) / 3600, 2),
            "active_days": len(days),
            "sessions": len(st),
            "hook_sessions": sum(1 for x in st if x["hook"]),
            "tasks": sum(x["tasks"] for x in st),
            "tagged_tasks": sum(len(x["tagged"]) for x in st),
            "rated_tasks": sum(x["rated"] for x in st),
            "top_category": cats.most_common(1)[0][0] if cats else None,
            "model_cost": {f: round(c, 2) for f, c in sorted(models.items(), key=lambda kv: -kv[1]) if round(c, 2)},
            "token_split": {name: split[name] for name, _ in SPLIT},
            "model_tokens": {f: n for f, n in sorted(model_tokens.items(), key=lambda kv: -kv[1]) if n},
            "agent_tokens": sum(v["agent_tokens"] for v in vols),
        }, days

    all_weeks = set(by_week) | {wk for x in per.values() for wk in x["volume"]}
    out_weeks = []
    for wk in sorted(all_weeks)[-weeks:]:
        ss = by_week.get(wk, [])
        t, _ = totals(ss, wk)
        t["leak_share"], t["waste_index"] = leak_shares(split_findings(findings, ss), ss)
        out_weeks.append({"week": wk, **t})

    cutoff = (datetime.now() - timedelta(days=DAILY_DAYS - 1)).date().isoformat()
    daily = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "active_s": 0.0})
    for x in per.values():
        for d, v in x["daily"].items():
            if d >= cutoff:
                for k in daily[d]:
                    daily[d][k] += v[k]
    out_days = [{"day": d, "tokens": v["tokens"], "cost_usd": round(v["cost"], 2),
                 "active_hours": round(v["active_s"] / 3600, 2)} for d, v in sorted(daily.items())]

    life, days = totals(sessions)
    life["first_day"] = min(days) if days else None
    life["longest_streak_days"] = longest_streak(days)
    life["leak_share"], life["waste_index"] = leak_shares(findings, sessions)
    return {"schema": SCHEMA, "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "lifetime": life, "weeks": out_weeks, "days": out_days}


def fmt_tokens(n):
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(n)


def summary(p):
    life = p["lifetime"]
    names = {n: name for n, (name, _, _) in leak_categories.CATEGORIES.items()}
    lines = ["# Your Claude Code, in numbers\n",
             f"Since {life['first_day']}:\n",
             f"- **{fmt_tokens(life['tokens'])} tokens** in {life['sessions']} sessions",
             f"- **${life['cost_usd']:,.2f}** API-equivalent spend",
             "- Tokens by type: " + ", ".join(f"{name.replace('_', ' ')} {fmt_tokens(n)} ({n / max(life['tokens'], 1):.0%})"
                                              for name, n in life["token_split"].items())
             + (f"; subagents {life['agent_tokens'] / max(life['tokens'], 1):.0%} of all tokens" if life["agent_tokens"] else ""),
             f"- **{life['active_hours']:,.1f} active hours** over {life['active_days']} days "
             f"(longest streak {life['longest_streak_days']} days)",
             f"- {life['tasks']} tasks, {life['tagged_tasks']} tagged, {life['rated_tasks']} rated"
             + (f", most often `{life['top_category']}`" if life["top_category"] else "")]
    if life["model_cost"] and life["cost_usd"]:
        mix = ", ".join(f"{f} {c / life['cost_usd']:.0%}" for f, c in life["model_cost"].items() if c)
        lines.append(f"- Model mix by spend: {mix}")
    top = sorted(life["leak_share"].items(), key=lambda kv: -kv[1])[:3]
    if top:
        lines.append("\nBiggest leaks: " + "; ".join(f"#{k} {names[int(k)]} ({v:.1%})" for k, v in top))
    if p["weeks"]:
        lines.append("\n| Week | Tokens | Spend | Active h | Sessions | Tagged | Rated | Waste index |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for w in p["weeks"]:
            lines.append(f"| {w['week']} | {fmt_tokens(w['tokens'])} | ${w['cost_usd']:,.2f} | {w['active_hours']:.1f} "
                         f"| {w['sessions']} | {w['tagged_tasks']} | {w['rated_tasks']} | {w['waste_index']:.2f} |")
        lines.append("\nWaste index sums the non-review leak shares; categories overlap, so compare it only week to week.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Claude Code usage summary and the share payload")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--events", default=os.path.expanduser("~/.claude/metrics/events.jsonl"))
    ap.add_argument("--weeks", type=int, default=PAYLOAD_WEEKS, help="weeks of detail in the payload")
    ap.add_argument("--json", action="store_true", help="print the share payload instead of the summary")
    a = ap.parse_args()
    p = build(a.root, a.events, a.weeks)
    if not p:
        print(f"no sessions found under {a.root}")
        return
    print(json.dumps(p, indent=2) if a.json else summary(p))


if __name__ == "__main__":
    main()
