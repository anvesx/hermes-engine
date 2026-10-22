#!/usr/bin/env python3
"""
metrics_hook.py - one Claude Code hook for every event we measure.

Appends one JSON line per event to ~/.claude/metrics/events.jsonl.
Never blocks Claude Code: any error exits 0 silently.

Extra commands you can type at the Claude Code prompt (handled here, never sent to the model):
  rate 3            frustration for the task just finished, 1 = smooth, 5 = very frustrating
  rate 4 fail       ...plus outcome: ok | partial | fail
Tag a new task by starting its prompt with a category:
  [bugfix] the date parser drops time zones

Cold-cache guard: the first prompt after the prompt cache expired in a big chat is held once, with
what sending it costs; sending it again goes through. `metrics_hook.py guard on|off|status` switches it
(also off with CC_METRICS_COLD_GUARD=0).
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

LOG_DIR = os.path.expanduser(os.environ.get("CC_METRICS_DIR", "~/.claude/metrics"))
KEEP_PROMPTS = os.environ.get("CC_METRICS_KEEP_PROMPTS") == "1"   # off by default for privacy
SYNC_EVERY_S = 60 * 60   # same throttle as share.py, checked here so most sessions spawn nothing
GUARD_FILE = os.path.join(LOG_DIR, "guard.json")   # cold-cache guard: on/off, and the cold periods already held
COLD_GUARD_MIN_USD = 0.50   # a re-cache cheaper than this is never held
TAIL_BYTES = 512 * 1024     # transcript tail read to find the last model call
TTL_S = {"5m": 300, "1h": 3600}

RATE_RE = re.compile(r"^\s*rate\s+([1-5])(?:\s+(ok|partial|fail))?\s*$", re.I)
TAG_RE = re.compile(r"^\s*\[([A-Za-z][\w-]*)\]")
CORRECTION_RE = re.compile(
    r"^\s*(no\b|nope\b|wrong\b|that'?s not|that is not|not what i|undo\b|revert\b|stop\b|"
    r"don'?t\b|you (broke|missed|forgot|ignored)|i said\b|again\b)", re.I)
REVERT_RE = re.compile(r"\bgit\s+(checkout\s+(--|\.)|restore\b|reset\s+--hard|revert\b|stash\b)")


def sync_report_scripts(only_if_missing=False):
    """Copy the report scripts to ~/.claude/metrics so they run from a fixed path after updates."""
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(LOG_DIR, exist_ok=True)
    for name in ("analyze.py", "leak_report.py", "leak_extra.py", "leak_categories.py", "stats.py", "share.py", "research.py",
                 "statusline.py"):
        src, dst = os.path.join(here, name), os.path.join(LOG_DIR, name)
        if only_if_missing and os.path.exists(dst):
            continue
        try:
            data = open(src, "rb").read()
            if not os.path.exists(dst) or open(dst, "rb").read() != data:
                with open(dst, "wb") as f:
                    f.write(data)
        except OSError:
            pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    ev = data.get("hook_event_name", "")
    rec = {"ts": time.time(), "event": ev, "session_id": data.get("session_id"),
           "transcript_path": data.get("transcript_path"), "cwd": data.get("cwd")}
    reply = None

    if ev == "UserPromptSubmit":
        prompt = data.get("prompt") or data.get("user_input") or ""
        m = RATE_RE.match(prompt)
        if m:
            rec.update(kind="rating", rating=int(m.group(1)), outcome=(m.group(2) or "").lower() or None)
            reply = {"decision": "block",
                     "reason": f"Recorded: frustration {m.group(1)}/5"
                               + (f", outcome {m.group(2).lower()}" if m.group(2) else "")
                               + ". Not sent to Claude."}
        else:
            tag = TAG_RE.match(prompt)
            rec.update(kind="prompt", category=tag.group(1).lower() if tag else None,
                       correction=bool(CORRECTION_RE.match(prompt)), prompt_chars=len(prompt))
            if KEEP_PROMPTS:
                rec["prompt"] = prompt[:500]
            try:
                held = cold_guard(data, prompt)
            except Exception:
                held = None
            if held:
                rec.update(cold_hold=True, recache_tokens=held[0])
                reply = held[1]

    elif ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        tool_input = data.get("tool_input") or {}
        rec.update(tool=data.get("tool_name"), tool_use_id=data.get("tool_use_id"))
        if data.get("tool_name") == "Bash":
            rec["git_revert"] = bool(REVERT_RE.search(str(tool_input.get("command", ""))))
        if ev == "PostToolUseFailure":
            rec["is_interrupt"] = bool(data.get("is_interrupt"))

    elif ev == "PreCompact":
        rec["trigger"] = data.get("trigger")          # auto or manual
    elif ev == "SessionStart":
        rec["source"] = data.get("source")
        sync_report_scripts()
    elif ev == "SessionEnd":
        rec["reason"] = data.get("reason")

    os.makedirs(LOG_DIR, exist_ok=True)
    if ev != "SessionStart":
        sync_report_scripts(only_if_missing=True)   # covers installs via /reload-plugins mid-session
    with open(os.path.join(LOG_DIR, "events.jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")
    if reply:
        print(json.dumps(reply))
    if ev == "SessionEnd":
        start_background_sync()


def load_guard():
    try:
        with open(GUARD_FILE) as f:
            g = json.load(f)
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def save_guard(g):
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = GUARD_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(g, f)
    os.replace(tmp, GUARD_FILE)


def last_call(path):
    """(time, context tokens, model, cache lifetime) of the transcript's last main-thread model call, or None.
    The lifetime comes from the latest call that wrote to the cache; without that split it is 1h."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().splitlines()
    found, ttl = None, None
    for raw in reversed(lines):
        if b'"assistant"' not in raw or b'"usage"' not in raw:
            continue
        try:
            e = json.loads(raw)
        except ValueError:   # the first line of the tail may be cut
            continue
        msg = e.get("message") or {}
        u = msg.get("usage")
        if e.get("type") != "assistant" or e.get("isSidechain") or not u or msg.get("model") == "<synthetic>":
            continue
        if found is None:
            t = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
            ctx = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            found = (t, ctx, msg.get("model", ""))
        split = u.get("cache_creation") or {}
        if split.get("ephemeral_1h_input_tokens"):
            ttl = "1h"
        elif split.get("ephemeral_5m_input_tokens"):
            ttl = "5m"
        if ttl:
            break
    return found and found + (ttl or "1h",)


def cold_guard(data, prompt):
    """Hold the first prompt after the prompt cache expired in a big chat, once, to show what sending it costs.
    Returns (tokens to re-cache, block reply) or None. Sending it again goes through: a held prompt makes
    no model call, so the same cold period is recognised by the time of the last call."""
    text = prompt.lstrip()
    if text.startswith("/") or (text.startswith("<") and not text.startswith("<pasted_content")):
        return None   # slash commands, and task notifications and other messages Claude Code sends itself
    if data.get("agent_id") or os.environ.get("CC_METRICS_COLD_GUARD") == "0":
        return None
    g = load_guard()
    if g.get("cold_guard") is False:
        return None
    call = last_call(data.get("transcript_path") or "")
    if not call:
        return None
    t, tokens, model, ttl = call
    idle = time.time() - t
    if idle < TTL_S[ttl]:
        return None
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import statusline
    cost = statusline.recache_cost(tokens, model, ttl)
    if not cost or cost[0] < COLD_GUARD_MIN_USD:
        return None
    key = f"{data.get('session_id')}:{t}"
    held = g.get("held") or []
    if key in held:
        return None
    g["held"] = (held + [key])[-50:]
    save_guard(g)
    h, m = divmod(int(idle // 60), 60)
    since = f"{h // 24}d {h % 24}h" if h >= 24 else f"{h}h {m}m" if h else f"{m} min"
    reason = (f"⏸ Held once: no reply for {since}, so the prompt cache ({ttl}) has expired.\n"
              f"Sending this re-writes ~{statusline.k(tokens)} tokens to the cache: ≈ {statusline.usd(cost[0])} at API prices "
              f"(≈ {statusline.usd(cost[1])} if it were still warm).\n"
              "  • Unrelated task?  /clear and start fresh, much cheaper.\n"
              "  • Same task?       Send it again; it goes through this time.\n"
              "Turn this check off: /token-metrics:cold-guard off")
    return tokens, {"decision": "block", "reason": reason}


def guard_command(args):
    """`metrics_hook.py guard on|off|status`, run by /token-metrics:cold-guard."""
    g = load_guard()
    if args and args[0] in ("on", "off"):
        g["cold_guard"] = args[0] == "on"
        save_guard(g)
    if os.environ.get("CC_METRICS_COLD_GUARD") == "0":
        print("Cold-cache guard is off (CC_METRICS_COLD_GUARD=0 is set in your environment).")
    elif g.get("cold_guard") is False:
        print("Cold-cache guard is off. `/token-metrics:cold-guard on` turns it back on.")
    else:
        print("Cold-cache guard is on: after a break long enough for the prompt cache to expire, the first message "
              f"in a chat that would cost ${COLD_GUARD_MIN_USD:.2f}+ to re-cache is held once, with the cost. "
              "Sending it again goes through. `/token-metrics:cold-guard off` turns it off.")


def start_background_sync():
    """If the user joined the leaderboard and the last sync is over an hour old, run share.py sync
    detached, so this hook returns immediately. share.py rechecks the throttle and holds a lock."""
    try:
        with open(os.path.join(LOG_DIR, "share.json")) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return
    if not cfg.get("token") or time.time() - cfg.get("last_sync", 0) < SYNC_EVERY_S:
        return
    script = os.path.join(LOG_DIR, "share.py")
    if os.path.exists(script):
        subprocess.Popen([sys.executable, script, "sync", "--background"], cwd=LOG_DIR,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["guard"]:
        guard_command(sys.argv[2:])
        sys.exit(0)
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
