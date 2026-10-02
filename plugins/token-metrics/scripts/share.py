#!/usr/bin/env python3
"""
share.py - opt-in sync of your aggregate stats to the company leaderboard.

Nothing leaves this machine until you join. After that, the SessionEnd hook runs `sync` in the
background at most once an hour. What is sent is exactly `python3 stats.py --json`: weekly totals
and each leak category's share of spend. No prompt text, project names, file paths or session ids.

  python3 share.py preview                       # what would be sent; sends nothing
  python3 share.py join you@devxlabs.ai          # emails you a 6-digit code
  python3 share.py verify 123456 "Your Name"     # finishes joining; background sync starts
  python3 share.py sync [--force]                # send now (the hook does this for you)
  python3 share.py me                            # points, level, rank, badges, card link
  python3 share.py leaderboard [--period week|month|all]
  python3 share.py card --hide spend,name        # choose what your public card shows
  python3 share.py leave                         # delete your data on the server and stop syncing

The server URL comes from CC_METRICS_SHARE_URL, else DEFAULT_URL below.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import stats

CLIENT = "token-metrics/1.3.0"
DEFAULT_URL = None                  # set to the deployed leaderboard URL before rolling out
DOMAIN = "devxlabs.ai"
SYNC_EVERY_S = 60 * 60
LOCK_STALE_S = 10 * 60
CARD_FIELDS = ("name", "level", "badges", "streak", "tokens", "hours", "spend")

LOG_DIR = os.path.expanduser(os.environ.get("CC_METRICS_DIR", "~/.claude/metrics"))
CONFIG = os.path.join(LOG_DIR, "share.json")
LOCK = os.path.join(LOG_DIR, "share.lock")
LOG = os.path.join(LOG_DIR, "share.log")


class Fail(Exception):
    pass


def load():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(cfg):
    os.makedirs(LOG_DIR, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def base_url(cfg):
    url = os.environ.get("CC_METRICS_SHARE_URL") or cfg.get("url") or DEFAULT_URL
    if not url:
        raise Fail("no leaderboard URL configured: set CC_METRICS_SHARE_URL")
    return url.rstrip("/")


def call(cfg, method, path, body=None, auth=True):
    headers = {"Content-Type": "application/json", "User-Agent": CLIENT}
    if auth:
        if not cfg.get("token"):
            raise Fail("not joined yet: run `share.py join you@" + DOMAIN + "`")
        headers["Authorization"] = "Bearer " + cfg["token"]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url(cfg) + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:
            msg = None
        if e.code == 401 and auth:
            raise Fail("the server no longer accepts your token: run `share.py join` again")
        raise Fail(msg or f"server returned HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Fail(f"could not reach {base_url(cfg)}: {getattr(e, 'reason', e)}")


def payload():
    p = stats.build(os.path.expanduser("~/.claude/projects"), os.path.join(LOG_DIR, "events.jsonl"))
    if not p:
        raise Fail("no Claude Code sessions found yet")
    return {"client": CLIENT, **p}


# ------------------------------------------------------------------ commands


def cmd_preview(a, cfg):
    print("This is exactly what `sync` sends. Nothing was sent.\n")
    print(json.dumps(payload(), indent=2))


def cmd_join(a, cfg):
    email = a.email.strip().lower()
    if not email.endswith("@" + DOMAIN):
        raise Fail(f"use your @{DOMAIN} work email")
    if a.url:
        cfg["url"] = a.url.rstrip("/")
    call(cfg, "POST", "/api/auth/start", {"email": email}, auth=False)
    cfg["email"] = email
    cfg.pop("token", None)
    save(cfg)
    print(f"A 6-digit code is on its way to {email}.\n")
    print("Joining shares, from now on and automatically about once an hour:")
    print("  weekly tokens, API-equivalent spend, active hours, active days, session/task counts,")
    print("  tagged and rated task counts, model mix by spend, and each leak category's share of spend.")
    print("It never shares prompt text, project names, file paths or session ids.")
    print("See the exact data with `share.py preview`. Your name and stats appear on the internal leaderboard;")
    print(f"your public card shows {', '.join(CARD_FIELDS)} until you hide some with `share.py card --hide ...`.\n")
    print('To agree and finish: /token-metrics:join verify <code> "Your Name"')


def cmd_verify(a, cfg):
    if not cfg.get("email"):
        raise Fail("run `share.py join you@" + DOMAIN + "` first")
    name = " ".join(a.name).strip() or cfg["email"].split("@")[0]
    r = call(cfg, "POST", "/api/auth/verify", {"email": cfg["email"], "code": a.code.strip(), "display_name": name},
             auth=False)
    cfg.update(token=r["token"], handle=r.get("handle"), display_name=name,
               consent_at=datetime.now().astimezone().isoformat(timespec="seconds"), last_sync=0)
    save(cfg)
    print(f"Joined as {name}. Sending your first sync...")
    try:
        sync(cfg, force=True)
    except Fail as e:
        print(f"The first sync failed ({e}); it will retry when a session ends, or run /token-metrics:share.")
    show_me(cfg)


def sync(cfg, force=False):
    """Send the payload. Returns False (and logs) instead of raising when run from the hook."""
    if not cfg.get("token"):
        return False
    if not force and time.time() - cfg.get("last_sync", 0) < SYNC_EVERY_S:
        return False
    try:
        fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        os.close(fd)
    except FileExistsError:
        if time.time() - os.path.getmtime(LOCK) < LOCK_STALE_S:
            return False          # another sync is running
        os.utime(LOCK)
    try:
        call(cfg, "POST", "/api/sync", payload())
        cfg = {**load(), "last_sync": time.time()}
        save(cfg)
        return True
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


def cmd_sync(a, cfg):
    if a.background:
        try:
            sync(cfg)
        except Exception as e:     # the hook must never surface errors
            log(f"sync failed: {e}")
        return
    print("synced" if sync(cfg, force=a.force) else "skipped: synced less than an hour ago (use --force)")


def show_me(cfg):
    me = call(cfg, "GET", "/api/me")
    lv = me.get("level", {})
    print(f"\n{me.get('display_name')}  -  level {lv.get('level')} ({lv.get('title')}), {me.get('points', 0):,} points")
    print(f"rank #{me.get('rank')} of {me.get('players')} this week  |  streak {me.get('streak_weeks', 0)} weeks")
    v = me.get("volume", {})
    print(f"{stats.fmt_tokens(v.get('tokens', 0))} tokens, {v.get('active_hours', 0):,.1f} active hours, "
          f"${v.get('cost_usd', 0):,.2f} API-equivalent spend (all time)")
    badges = me.get("badges", [])
    if badges:
        print("badges: " + ", ".join(b["name"] for b in badges))
    nxt = me.get("next_badges", [])
    if nxt:
        print("next: " + "; ".join(f"{b['name']} ({b['hint']})" for b in nxt[:3]))
    if me.get("profile_url"):
        print(f"\npublic card: {me['profile_url']}  (post this link; the card image previews automatically)")


def cmd_me(a, cfg):
    show_me(cfg)


def cmd_leaderboard(a, cfg):
    r = call(cfg, "GET", f"/api/leaderboard?period={a.period}")
    print(f"| # | Name | Level | Points ({a.period}) | Streak | Tokens | Active h |")
    print("|---|---|---|---|---|---|---|")
    for row in r.get("rows", [])[:a.top]:
        me = " (you)" if row.get("handle") == cfg.get("handle") else ""
        print(f"| {row['rank']} | {row['display_name']}{me} | {row['level']} | {row['points']:,} | "
              f"{row['streak_weeks']}w | {stats.fmt_tokens(row['tokens'])} | {row['active_hours']:,.1f} |")
    if r.get("url"):
        print(f"\nfull leaderboard: {r['url']}")


def cmd_card(a, cfg):
    fields = dict(call(cfg, "GET", "/api/me").get("card_fields") or {f: True for f in CARD_FIELDS})
    for opt, value in ((a.hide, False), (a.show, True)):
        for f in filter(None, (x.strip() for x in (opt or "").split(","))):
            if f not in CARD_FIELDS:
                raise Fail(f"unknown field {f!r}; choose from {', '.join(CARD_FIELDS)}")
            fields[f] = value
    if a.hide or a.show:
        call(cfg, "PATCH", "/api/me", {"card_fields": fields})
    print("public card shows: " + (", ".join(f for f in CARD_FIELDS if fields.get(f)) or "nothing"))


def cmd_leave(a, cfg):
    if cfg.get("token"):
        call(cfg, "DELETE", "/api/me")
    if os.path.exists(CONFIG):
        os.remove(CONFIG)
    print("Left: your data was deleted from the server and syncing stopped.")


def main():
    ap = argparse.ArgumentParser(description="Opt-in sync to the token-metrics leaderboard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preview")
    p = sub.add_parser("join")
    p.add_argument("email")
    p.add_argument("--url", help="leaderboard URL (else CC_METRICS_SHARE_URL)")
    p = sub.add_parser("verify")
    p.add_argument("code")
    p.add_argument("name", nargs="*")
    p = sub.add_parser("sync")
    p.add_argument("--force", action="store_true")
    p.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("me")
    p = sub.add_parser("leaderboard")
    p.add_argument("--period", choices=["week", "month", "all"], default="week")
    p.add_argument("--top", type=int, default=15)
    p = sub.add_parser("card")
    p.add_argument("--hide")
    p.add_argument("--show")
    sub.add_parser("leave")
    a = ap.parse_args()
    try:
        globals()["cmd_" + a.cmd](a, load())
    except Fail as e:
        print(f"token-metrics: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
