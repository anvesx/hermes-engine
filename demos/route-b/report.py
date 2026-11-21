#!/usr/bin/env python3
"""Summarise Route B delegations from <metrics dir>/delegations.jsonl.

  python3 report.py                    # table of every delegation
  python3 report.py --price-in 0.5 --price-out 3     # add cost, USD per million tokens (enter current list prices)
"""
import argparse
import json
import os
import time
from pathlib import Path

LOG = Path(os.environ.get("CC_METRICS_DIR", Path.home() / ".claude" / "metrics")) / "delegations.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price-in", type=float, help="USD per million input tokens")
    ap.add_argument("--price-out", type=float, help="USD per million output + thinking tokens")
    a = ap.parse_args()
    if not LOG.exists():
        print(f"No delegations yet ({LOG}).")
        return
    rows, outcome = [], {}
    for line in LOG.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") == "delegated":
            rows.append(r)
        elif r.get("event") in ("merged", "discarded"):
            outcome[r["id"]] = r["event"]
    priced = a.price_in is not None and a.price_out is not None
    head = f"{'when':<12} {'task':<28} {'type':<9} {'model':<24} {'status':<8} {'secs':>5} {'in':>8} {'out':>7} " \
           f"{'checks':<7} {'diff':<9} {'result':<9}" + (f" {'cost':>8}" if priced else "")
    print(head)
    print("-" * len(head))
    tot_in = tot_out = tot_cost = 0
    merged = passed = 0
    for r in rows:
        u = r.get("usage") or {}
        tin = u.get("input_tokens", 0) or 0
        tout = (u.get("output_tokens", 0) or 0) + (u.get("thinking_tokens", 0) or 0)
        tot_in, tot_out = tot_in + tin, tot_out + tout
        cp = r.get("checks_passed")
        checks = "-" if cp is None else ("pass" if cp else "FAIL")
        passed += cp is True
        res = outcome.get(r["id"], "pending")
        merged += res == "merged"
        line = (f"{time.strftime('%d %b %H:%M', time.localtime(r['ts'])):<12} {r['label'][:28]:<28} "
                f"{r.get('category', ''):<9} {r['model'][:24]:<24} {r['status'][:8]:<8} {r['seconds']:>5.0f} "
                f"{tin:>8,} {tout:>7,} {checks:<7} {'+%d -%d' % (r['added'], r['removed']):<9} {res:<9}")
        if priced:
            cost = tin / 1e6 * a.price_in + tout / 1e6 * a.price_out
            tot_cost += cost
            line += f" ${cost:>7.4f}"
        print(line)
    print("-" * len(head))
    print(f"{len(rows)} delegated · {passed} passed checks · {merged} merged · "
          f"{tot_in:,} input + {tot_out:,} output tokens on Gemini" + (f" · ${tot_cost:.4f}" if priced else ""))


if __name__ == "__main__":
    main()
