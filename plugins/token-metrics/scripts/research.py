#!/usr/bin/env python3
"""
research.py - an anonymous, aggregate-only export of your Claude Code token data, for the team's token-leak
study, and the tool that pools everyone's exports.

  python3 research.py export [--out FILE]      # writes one JSON file; send it to whoever runs the study
  python3 research.py preview                  # prints what export would write; writes nothing
  python3 research.py merge A.json B.json ...  # pools exports into the study's numbers (--json for raw)

What an export contains: totals and shares (tokens and spend by type and model, the 50 leak categories),
per-session sizes with no ids or times (in random order), cache-break counts, and the measured characters per
token. What it never contains: prompt or reply text, tool output, file paths, project names, session ids,
timestamps, your name or email. Each export carries a random id so a file isn't counted twice.

Everything is computed with leak_report.py's parser and cost model over all transcripts on disk.
"""
import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime

import leak_categories
import leak_report

FORMAT = 1
CLIENT = "token-metrics/1.5.7"
CTX_BUCKETS = ((0, 100_000), (100_000, 250_000), (250_000, 500_000), (500_000, float("inf")))
GAP_BUCKETS_MIN = ((5, 60), (60, 180), (180, 720), (720, float("inf")))   # idle gap before a full cache rewrite
TOKEN_TYPES = (("input", "in"), ("cache_write", "cw"), ("cache_read", "cr"), ("output", "out"))


def bucket_label(lo, hi, unit=""):
    f = lambda x: f"{int(x / 1000)}k" if unit == "" else f"{int(x)}"
    return f"{f(lo)}+{unit}" if hi == float("inf") else f"{f(lo)}-{f(hi)}{unit}"


def collect(root, events):
    hook_prompts, _ = leak_report.load_hook_prompts(events)
    findings = defaultdict(list)
    for sid, entries in leak_report.load_sessions(root, 0).items():
        leak_report.analyse(leak_report.Session(sid, entries, 2.0, 3600, hook_prompts), findings)
    if findings["_sessions"]:
        leak_report.cross_session(findings)
    return findings


def export(root, events):
    f = collect(root, events)
    ss = [s for s in f["_sessions"] if s.calls]
    if not ss:
        return None
    calls = [c for s in ss for c in s.calls + s.helper_calls]
    main = [c for s in ss for c in s.calls]
    total = sum(c["cost"] for c in calls)

    tokens, usd, by_model = Counter(), Counter(), defaultdict(Counter)
    for c in calls:
        pi, po, pr = leak_report.price(c["model"])
        cost = {"in": c["in"] * pi, "cw": c["cw"] * pi * c["wmult"], "cr": c["cr"] * pr, "out": c["out"] * po}
        for name, k in TOKEN_TYPES:
            tokens[name] += c[k]
            usd[name] += cost[k] / 1e6
        model = next((k for k in leak_report.PRICE_IDS if k in c["model"].lower()), "other")
        by_model[model]["tokens"] += c["ctx"] + c["out"]
        by_model[model]["usd"] += c["cost"]

    ctx_buckets = []
    for lo, hi in CTX_BUCKETS:
        b = [c for c in main if lo <= c["ctx"] < hi]
        ctx_buckets.append({"ctx": bucket_label(lo, hi), "calls": len(b), "usd": round(sum(c["cost"] for c in b), 2)})

    # full-context rewrites after an idle gap, by gap length (same rule as leak 3/3a: cw > max(5k, half the context))
    gaps = []
    for s in ss:
        for a, b in zip(s.calls, s.calls[1:]):
            if (b["cw"] > max(5_000, 0.5 * b["ctx"]) and a["model"] == b["model"]
                    and not any(a["t"] < x <= b["t"] for x in s.comp_sorted)):
                pi, _, pr = leak_report.price(b["model"])
                gaps.append(((b["t"] - a["t"]) / 60, b["cw"] * (pi * b["wmult"] - pr) / 1e6, b["ctx"]))
    gap_buckets = []
    for lo, hi in GAP_BUCKETS_MIN:
        g = [x for x in gaps if lo <= x[0] < hi]
        gap_buckets.append({"gap": bucket_label(lo, hi, " min"), "rewrites": len(g), "usd": round(sum(x[1] for x in g), 2),
                            "median_ctx": int(statistics.median(x[2] for x in g)) if g else 0})

    hooked = set(f["_hook_sessions"])
    sessions = [{"first_ctx": s.calls[0]["ctx"], "peak_ctx": max(c["ctx"] for c in s.calls),
                 "main_calls": len(s.calls), "helper_calls": len(s.helper_calls),
                 "span_hours": round((s.calls[-1]["t"] - s.calls[0]["t"]) / 3600, 1),
                 "compactions": len(s.compactions), "usd": round(s.cost + s.helper_cost, 2),
                 "hooked": s.sid in hooked} for s in ss]
    # the same transcripts give the same fingerprint, so a person exporting twice isn't counted twice
    fingerprint = hashlib.sha256(json.dumps(sorted(json.dumps(x, sort_keys=True) for x in sessions)).encode()).hexdigest()
    random.shuffle(sessions)

    categories = []
    for n, name, group, cost, items, reason, note in leak_report.curated_rows(f, total, ss):
        categories.append({"n": n, "name": name, "group": group, "review": n in leak_categories.REVIEW,
                           "measurable": reason is None, "usd": round(cost, 2) if reason is None else None,
                           "share": round(cost / total, 5) if reason is None and total else None,
                           "instances": len(items) if reason is None else None})
    categories.sort(key=lambda c: c["n"])

    # the same categories counted in tokens (every token weighs 1; cache categories become tokens written)
    leak_report.set_units("tokens")
    try:
        ft = collect(root, events)
        st = [s for s in ft["_sessions"] if s.calls]
        ttotal = sum(s.cost + s.helper_cost for s in st)
        categories_tokens = sorted(({"n": n, "measurable": reason is None,
                                     "tokens": round(cost) if reason is None else None,
                                     "share": round(cost / ttotal, 5) if reason is None and ttotal else None,
                                     "cache_event": n in leak_categories.CACHE_EVENTS}
                                    for n, name, group, cost, items, reason, note in leak_report.curated_rows(ft, ttotal, st)),
                                   key=lambda c: c["n"])
    finally:
        leak_report.set_units("usd")

    calib = defaultdict(list)
    for s in ss:
        for model, v in getattr(s, "calibration_samples", {}).items():
            calib[leak_report.tokenizer(model)] += v
    days = {datetime.fromtimestamp(c["t"]).date() for c in calls}

    return {
        "format": FORMAT, "client": CLIENT, "export_id": uuid.uuid4().hex, "fingerprint": fingerprint,
        "coverage": {"sessions": len(ss), "active_days": len(days),
                     "days_spanned": (max(days) - min(days)).days + 1 if days else 0,
                     "hooked_sessions": len(hooked)},
        "calls": {"main": len(main), "helper": len(calls) - len(main)},
        "tokens": dict(tokens), "usd": {k: round(v, 2) for k, v in usd.items()}, "usd_total": round(total, 2),
        "by_model": {m: {"tokens": v["tokens"], "usd": round(v["usd"], 2)} for m, v in by_model.items()},
        "helper_usd": round(sum(s.helper_cost for s in ss), 2),
        "ctx_buckets": ctx_buckets, "rewrite_gaps": gap_buckets,
        "sessions": sessions, "categories": categories, "categories_tokens": categories_tokens,
        "chars_per_token": {k: {"median": round(statistics.median(v), 3), "samples": len(v)} for k, v in calib.items()},
    }


# ------------------------------------------------------------------ merge


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else None


def spread(xs):
    """median and interquartile range across contributors"""
    xs = [x for x in xs if x is not None]
    return {"median": q(xs, 0.5), "p25": q(xs, 0.25), "p75": q(xs, 0.75), "n": len(xs)} if xs else None


def merge(paths):
    exports, seen = [], set()
    for p in paths:
        with open(p) as fh:
            e = json.load(fh)
        if e.get("format") != FORMAT:
            sys.exit(f"{p}: unsupported export format {e.get('format')}")
        if e["export_id"] in seen or e.get("fingerprint") in seen:
            print(f"skipped {p}: same data as an earlier file", file=sys.stderr)
            continue
        seen.update({e["export_id"], e.get("fingerprint")} - {None})
        exports.append(e)
    total = sum(e["usd_total"] for e in exports)
    tok = Counter()
    usd = Counter()
    for e in exports:
        tok.update(e["tokens"])
        usd.update(e["usd"])
    alltok = sum(tok.values())
    sessions = [s for e in exports for s in e["sessions"]]
    cats = defaultdict(lambda: {"usd": 0.0, "shares": []})
    meta = {}
    for e in exports:
        for c in e["categories"]:
            meta[c["n"]] = c
            if c["measurable"]:
                cats[c["n"]]["usd"] += c["usd"]
                cats[c["n"]]["shares"].append(c["share"])
    # token categories exist only in exports from 1.5.5 on; their shares must use only those exports' tokens
    with_tokens = [e for e in exports if "categories_tokens" in e]
    tok_with = sum(sum(e["tokens"].values()) for e in with_tokens)
    tcats = defaultdict(lambda: {"tokens": 0, "shares": []})
    for e in with_tokens:
        for c in e["categories_tokens"]:
            if c["measurable"]:
                tcats[c["n"]]["tokens"] += c["tokens"]
                tcats[c["n"]]["shares"].append(c["share"])
    gaps = defaultdict(lambda: {"rewrites": 0, "usd": 0.0})
    for e in exports:
        for g in e["rewrite_gaps"]:
            gaps[g["gap"]]["rewrites"] += g["rewrites"]
            gaps[g["gap"]]["usd"] += g["usd"]
    ctx = defaultdict(lambda: {"calls": 0, "usd": 0.0})
    for e in exports:
        for b in e["ctx_buckets"]:
            ctx[b["ctx"]]["calls"] += b["calls"]
            ctx[b["ctx"]]["usd"] += b["usd"]
    calib = defaultdict(list)
    for e in exports:
        for k, v in e["chars_per_token"].items():
            calib[k].append(v)
    return {
        "contributors": len(exports), "sessions": len(sessions),
        "main_calls": sum(e["calls"]["main"] for e in exports), "helper_calls": sum(e["calls"]["helper"] for e in exports),
        "tokens": alltok, "usd_total": round(total, 2),
        "token_share": {k: round(v / alltok, 4) for k, v in tok.items()} if alltok else {},
        "usd_share": {k: round(v / total, 4) for k, v in usd.items()} if total else {},
        "usd_share_by_contributor": {k: spread([e["usd"][k] / e["usd_total"] for e in exports if e["usd_total"]])
                                     for k in usd},
        "ctx_buckets": {k: {"calls": v["calls"], "usd": round(v["usd"], 2), "share_usd": round(v["usd"] / total, 4)}
                        for k, v in ctx.items()},
        "rewrite_gaps": {k: {"rewrites": v["rewrites"], "usd": round(v["usd"], 2)} for k, v in gaps.items()},
        "session_shape": {k: spread([s[k] for s in sessions])
                          for k in ("first_ctx", "peak_ctx", "main_calls", "span_hours", "usd")},
        "hooked_session_share": round(sum(s["hooked"] for s in sessions) / len(sessions), 3) if sessions else 0,
        "categories": sorted(({"n": n, "name": meta[n]["name"], "group": meta[n]["group"], "review": meta[n]["review"],
                               "usd": round(v["usd"], 2), "pooled_share": round(v["usd"] / total, 4) if total else 0,
                               "share_by_contributor": spread(v["shares"])}
                              for n, v in cats.items()), key=lambda c: -c["usd"]),
        "contributors_with_token_categories": len(with_tokens),
        "categories_tokens": sorted(({"n": n, "name": meta[n]["name"], "group": meta[n]["group"], "review": meta[n]["review"],
                                      "cache_event": n in leak_categories.CACHE_EVENTS, "tokens": v["tokens"],
                                      "pooled_share": round(v["tokens"] / tok_with, 4) if tok_with else 0,
                                      "share_by_contributor": spread(v["shares"])}
                                     for n, v in tcats.items()), key=lambda c: -c["tokens"]),
        "chars_per_token": {k: {"pooled_median_of_medians": q([x["median"] for x in v], 0.5),
                                "samples": sum(x["samples"] for x in v), "contributors": len(v)} for k, v in calib.items()},
    }


def merge_text(m):
    pct = lambda x: f"{x:.1%}" if x is not None else "-"
    lines = [f"# Pooled token data: {m['contributors']} contributor{'s' if m['contributors'] != 1 else ''}, {m['sessions']} sessions",
             f"{m['main_calls'] + m['helper_calls']:,} model calls, {m['tokens']:,} tokens, ${m['usd_total']:,.2f} API-equivalent\n",
             "| Token type | Share of tokens | Share of spend | Spend share, median (IQR) across contributors |",
             "|---|---|---|---|"]
    for k in ("cache_read", "cache_write", "output", "input"):
        s = m["usd_share_by_contributor"].get(k)
        lines.append(f"| {k} | {pct(m['token_share'].get(k))} | {pct(m['usd_share'].get(k))} | "
                     + (f"{pct(s['median'])} ({pct(s['p25'])}-{pct(s['p75'])})" if s else "-") + " |")
    if m["categories_tokens"]:
        lines += [f"\nToken categories come from {m['contributors_with_token_categories']} of {m['contributors']} contributors "
                  "(exports from token-metrics 1.5.5 on); their shares use only those contributors' tokens.",
                  "\n| Category (tokens) | Pooled tokens | Pooled share | Share, median (IQR) across contributors |", "|---|---|---|---|"]
        for c in m["categories_tokens"][:20]:
            s = c["share_by_contributor"]
            tag = " (cache event)" if c["cache_event"] else " (review)" if c["review"] else ""
            lines.append(f"| {c['n']}. {c['name']}{tag} | {c['tokens'] / 1e6:,.1f}M | {pct(c['pooled_share'])} | "
                         f"{pct(s['median'])} ({pct(s['p25'])}-{pct(s['p75'])}) |")
    lines += ["\n| Category (API-equivalent $) | Pooled cost | Pooled share | Share, median (IQR) across contributors |", "|---|---|---|---|"]
    for c in m["categories"][:20]:
        s = c["share_by_contributor"]
        lines.append(f"| {c['n']}. {c['name']}{' (review)' if c['review'] else ''} | ${c['usd']:,.2f} | "
                     f"{pct(c['pooled_share'])} | {pct(s['median'])} ({pct(s['p25'])}-{pct(s['p75'])}) |")
    sh = m["session_shape"]
    lines.append("\nSession shape, median (IQR): " + "; ".join(
        f"{k} {sh[k]['median']:,} ({sh[k]['p25']:,}-{sh[k]['p75']:,})" for k in sh if sh[k]))
    lines.append("Characters per token: " + "; ".join(
        f"{k} tokenizer {v['pooled_median_of_medians']:.2f} ({v['samples']} samples, {v['contributors']} contributors)"
        for k, v in m["chars_per_token"].items()))
    lines.append(f"Sessions with hook data: {m['hooked_session_share']:.0%}")
    lines.append("\nCategory costs overlap, so they don't add up to the total.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Anonymous aggregate export for the token-leak study, and the merge tool")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("export", "preview"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
        p.add_argument("--events", default=os.path.expanduser("~/.claude/metrics/events.jsonl"))
        if name == "export":
            p.add_argument("--out", help="output file (default: ~/Desktop or your home folder)")
    p = sub.add_parser("merge")
    p.add_argument("files", nargs="+")
    p.add_argument("--json", action="store_true", help="print the pooled numbers as JSON")
    a = ap.parse_args()

    if a.cmd == "merge":
        m = merge(a.files)
        print(json.dumps(m, indent=1) if a.json else merge_text(m))
        return
    e = export(a.root, a.events)
    if not e:
        print(f"no Claude Code sessions found under {a.root}")
        return
    if a.cmd == "preview":
        print(json.dumps(e, indent=1))
        return
    desk = os.path.expanduser("~/Desktop")
    out = a.out or os.path.join(desk if os.path.isdir(desk) else os.path.expanduser("~"),
                                f"token-study-{datetime.now():%Y%m%d}-{e['export_id'][:6]}.json")
    with open(out, "w") as fh:
        json.dump(e, fh, indent=1)
    print(f"Wrote {out}")
    print(f"{e['coverage']['sessions']} sessions over {e['coverage']['active_days']} active days, "
          f"${e['usd_total']:,.2f} API-equivalent.")
    print("It holds totals, shares and per-session sizes only: no prompts, code, paths, project names, "
          "session ids, timestamps or your name. Open it to check, then send the file to the study owner.")


if __name__ == "__main__":
    main()
