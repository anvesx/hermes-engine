#!/usr/bin/env python3
"""
guards.py - stop the token leaks a hook can see coming, called by metrics_hook.py.

Each guard holds an action once, saying what it costs and what to do instead; repeating the same action
goes through, so nobody gets stuck. A held prompt or tool call never reaches the model or the tool.

  cold         first prompt after the prompt cache expired in a big chat        (leak 04)
  new-task     a [tag]ged new task started in a chat carrying old history       (leak 08)
  size         notice, never a hold: the chat crossed 150k / 300k tokens         (leaks 06, 11, 17)
  big-read     Read of a whole large file without offset/limit                   (leak 24)
  fork         a fork agent copying a big chat into its own context             (leak 13)

`metrics_hook.py guards [name] [on|off]` switches them; CC_METRICS_GUARDS=0 turns all of them off.
Every guard returns None on any doubt: the hook must never break Claude Code.
"""
import json
import os
import re
import sys
import time
from datetime import datetime

LOG_DIR = os.path.expanduser(os.environ.get("CC_METRICS_DIR", "~/.claude/metrics"))
GUARD_FILE = os.path.join(LOG_DIR, "guard.json")   # which guards are off, and the actions already held
TAIL_BYTES = 512 * 1024     # transcript tail read to find the last model call
HEAD_BYTES = 1024 * 1024    # transcript head read to find the first model call
TTL_S = {"5m": 300, "1h": 3600}
HELD_KEEP = 200             # held-action keys remembered, newest kept

NAMES = ("cold", "new-task", "size", "big-read", "fork")
COLD_MIN_USD = 0.50         # a re-cache cheaper than this is never held
CARRY_MIN = 20_000          # old history a [tag]ged new task must carry to be held, as leak_report.CARRY_MIN
SIZE_NOTICES = (150_000, 300_000)   # chat sizes that get a one-time notice per session
# A held Read costs one extra model call, so only files well past leak_report.BIG_RESULT (4k) are held
BIG_READ = 8_000
DEP_READ = 2_000            # lower bar for dependency folders, lockfiles and minified files
CHARS_PER_TOKEN = 3.10      # bytes per token, the lower of leak_report.CHARS_PER_TOKEN: under-counts, never over
FORK_MIN = 50_000           # main chat size where a fork copies too much, as leak_report.FORK_MIN

TAG_RE = re.compile(r"^\s*\[([A-Za-z][\w-]*)\]")
DEP_PATH = re.compile(r"(^|/)(node_modules|\.venv|venv|dist|build|target|\.next|vendor|__pycache__)/"
                      r"|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|"
                      r"Gemfile\.lock|composer\.lock|uv\.lock)$|\.min\.(js|css)$")
NOT_TEXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb")


def load():
    try:
        with open(GUARD_FILE) as f:
            g = json.load(f)
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def save(g):
    os.makedirs(LOG_DIR, exist_ok=True)
    tmp = f"{GUARD_FILE}.{os.getpid()}.tmp"   # tool hooks run in parallel: each writes its own temp file
    with open(tmp, "w") as f:
        json.dump(g, f)
    os.replace(tmp, GUARD_FILE)


def is_on(g, name):
    if os.environ.get("CC_METRICS_GUARDS") == "0":
        return False
    if name == "cold" and (os.environ.get("CC_METRICS_COLD_GUARD") == "0" or g.get("cold_guard") is False):
        return False
    return name not in (g.get("off") or [])


def hold_once(g, key):
    """True the first time `key` is seen (and remembers it), False after."""
    held = g.get("held") or []
    if key in held:
        return False
    g["held"] = (held + [key])[-HELD_KEEP:]
    save(g)
    return True


def main_call(raw):
    """(time, context tokens, usage, model) of a transcript line if it is a main-thread model call."""
    if b'"assistant"' not in raw or b'"usage"' not in raw:
        return None
    try:
        e = json.loads(raw)
    except ValueError:   # the first line of a tail may be cut
        return None
    msg = e.get("message") or {}
    u = msg.get("usage")
    if e.get("type") != "assistant" or e.get("isSidechain") or not u or msg.get("model") == "<synthetic>":
        return None
    t = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).timestamp()
    ctx = sum(u.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return t, ctx, u, msg.get("model", "")


def last_call(path):
    """(time, context tokens, model, cache lifetime) of the transcript's last main-thread model call, or None.
    The lifetime comes from the latest call that wrote to the cache; without that split it is 1h."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        lines = f.read().splitlines()
    found, ttl = None, None
    for raw in reversed(lines):
        c = main_call(raw)
        if not c:
            continue
        if found is None:
            found = (c[0], c[1], c[3])
        split = c[2].get("cache_creation") or {}
        if split.get("ephemeral_1h_input_tokens"):
            ttl = "1h"
        elif split.get("ephemeral_5m_input_tokens"):
            ttl = "5m"
        if ttl:
            break
    return found and found + (ttl or "1h",)


def first_ctx(path):
    """Context tokens of the transcript's first main-thread model call: the chat's starting setup."""
    with open(path, "rb") as f:
        for raw in f.read(HEAD_BYTES).splitlines():
            c = main_call(raw)
            if c:
                return c[1]
    return None


def statusline():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import statusline as sl
    return sl


# ---------------------------------------------------------------- prompts

def prompt_guards(data, prompt):
    """(guard name, reply) for a UserPromptSubmit, or None. Holds take precedence over the size notice."""
    text = prompt.lstrip()
    if text.startswith("/") or (text.startswith("<") and not text.startswith("<pasted_content")):
        return None   # slash commands, and task notifications and other messages Claude Code sends itself
    if data.get("agent_id"):
        return None
    g = load()
    if not any(is_on(g, n) for n in ("cold", "new-task", "size")):
        return None
    call = last_call(data.get("transcript_path") or "")
    if not call:
        return None
    for name, guard in (("cold", cold), ("new-task", new_task), ("size", size_notice)):
        if is_on(g, name):
            reply = guard(g, data, text, call)
            if reply:
                return name, reply
    return None


def cold(g, data, text, call):
    """Hold the first prompt after the prompt cache expired in a big chat, once, to show what sending it costs.
    Sending it again goes through: a held prompt makes no model call, so the same cold period is
    recognised by the time of the last call."""
    t, tokens, model, ttl = call
    idle = time.time() - t
    if idle < TTL_S[ttl]:
        return None
    sl = statusline()
    cost = sl.recache_cost(tokens, model, ttl)
    if not cost or cost[0] < COLD_MIN_USD or not hold_once(g, f"{data.get('session_id')}:{t}"):
        return None
    h, m = divmod(int(idle // 60), 60)
    since = f"{h // 24}d {h % 24}h" if h >= 24 else f"{h}h {m}m" if h else f"{m} min"
    return {"decision": "block", "reason":
            f"⏸ Held once: no reply for {since}, so the prompt cache ({ttl}) has expired.\n"
            f"Sending this re-writes ~{sl.k(tokens)} tokens to the cache: ≈ {sl.usd(cost[0])} at API prices "
            f"(≈ {sl.usd(cost[1])} if it were still warm).\n"
            "  • Unrelated task?  /clear and start fresh, much cheaper.\n"
            "  • Same task?       Send it again; it goes through this time.\n"
            "Turn this check off: /token-metrics:guards cold off"}


def new_task(g, data, text, call):
    """Hold a [tag]ged prompt, which says a new task starts, when the chat already carries old history."""
    tag = TAG_RE.match(text)
    if not tag:
        return None
    t, tokens, model, _ = call
    start = first_ctx(data.get("transcript_path") or "") or 0
    carried = tokens - start
    if carried < CARRY_MIN or not hold_once(g, f"{data.get('session_id')}:task:{t}"):
        return None
    sl = statusline()
    p = sl.prices(model)
    each = f" ≈ {sl.usd(carried * p[2] / 1e6)} on every message" if p else " on every message"
    return {"decision": "block", "reason":
            f"⏸ Held once: [{tag.group(1)}] starts a new task, but this chat still carries ~{sl.k(carried)} tokens "
            f"of earlier work. Claude re-reads it{each} of the new task.\n"
            "  • Unrelated to the earlier work?  /clear, then send it again.\n"
            "  • Builds on it?                   Send it again; it goes through this time.\n"
            "Turn this check off: /token-metrics:guards new-task off"}


def size_notice(g, data, text, call):
    """A one-time notice per session and threshold when the chat grows past SIZE_NOTICES. Never holds."""
    _, tokens, model, _ = call
    line = max((n for n in SIZE_NOTICES if tokens >= n), default=None)
    if not line or not hold_once(g, f"{data.get('session_id')}:size:{line}"):
        return None
    sl = statusline()
    p = sl.prices(model)
    each = f" (≈ {sl.usd(tokens * p[2] / 1e6)} per message)" if p else ""
    return {"systemMessage": f"token-metrics: this chat is ~{sl.k(tokens)} tokens and every message re-reads all "
                             f"of it{each}. /compact keeps the gist; /clear if the next task is unrelated."}


# ---------------------------------------------------------------- tool calls

def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def tool_guards(data):
    """(guard name, reply) for a PreToolUse, or None."""
    if os.environ.get("CC_METRICS_GUARDS") == "0":
        return None
    tool = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    if tool == "Read":
        return big_read(data, inp)
    if tool in ("Agent", "Task") and inp.get("subagent_type") == "fork":
        return fork(data)
    return None


def big_read(data, inp):
    """Hold a whole-file Read of a large file once per session and file."""
    if inp.get("offset") is not None or inp.get("limit") is not None:
        return None
    path = str(inp.get("file_path") or "")
    if not path or path.lower().endswith(NOT_TEXT):
        return None
    path = os.path.join(data.get("cwd") or "", os.path.expanduser(path))
    try:
        tokens = int(os.path.getsize(path) / CHARS_PER_TOKEN)
    except OSError:
        return None
    dep = bool(DEP_PATH.search(path))
    if tokens < (DEP_READ if dep else BIG_READ):
        return None
    g = load()
    if not is_on(g, "big-read") or not hold_once(g, f"{data.get('session_id')}:read:{path}"):
        return None
    why = ("It is a dependency, build output, lockfile or minified file, which is rarely worth reading whole. "
           if dep else "")
    return "big-read", deny(
        f"token-metrics held this once: {os.path.basename(path)} is ~{tokens // 1000}k+ tokens, and a whole-file "
        f"Read stays in the chat and is re-read on every later message. {why}Grep for what you need, or Read "
        "only the relevant part with offset/limit. If you really need the whole file, re-issue the same Read; "
        "it goes through.")


def fork(data):
    """Hold a fork agent once per session when the main chat is big enough that copying it is expensive."""
    try:
        call = last_call(data.get("transcript_path") or "")
    except OSError:
        return None
    if not call or call[1] < FORK_MIN:
        return None
    g = load()
    if not is_on(g, "fork") or not hold_once(g, f"{data.get('session_id')}:fork"):
        return None
    k = statusline().k
    return "fork", deny(
        f"token-metrics held this once: a fork copies this whole ~{k(call[1])}-token chat into the agent, which "
        "re-reads it on every one of its messages. Prefer a fresh agent (e.g. general-purpose or Explore) with a "
        "short, self-contained brief: the goal, the files that matter and what you already know. If the agent "
        "truly needs the full conversation, re-issue the fork; it goes through.")


# ---------------------------------------------------------------- commands

SUMMARY = {
    "cold": "after a break long enough for the prompt cache to expire, holds the first message once with the "
            f"cost of re-caching the chat (when that is ${COLD_MIN_USD:.2f}+)",
    "new-task": f"holds a [tag]ged prompt once when the chat carries {CARRY_MIN // 1000}k+ tokens of earlier work",
    "size": "tells you once when the chat passes " + " and ".join(f"{n // 1000}k" for n in SIZE_NOTICES) + " tokens",
    "big-read": f"asks Claude once to Grep or read part of a file over ~{BIG_READ // 1000}k tokens "
                f"({DEP_READ // 1000}k for dependencies, lockfiles and minified files)",
    "fork": f"asks Claude once to brief a fresh agent instead of forking a chat over {FORK_MIN // 1000}k tokens",
}


def command(args):
    """`metrics_hook.py guards [name] [on|off]`, run by /token-metrics:guards."""
    g = load()
    names = [a for a in args if a in NAMES]
    switch = next((a for a in args if a in ("on", "off")), None)
    bad = [a for a in args if a not in NAMES and a not in ("on", "off")]
    if bad:
        print(f"Unknown guard: {', '.join(bad)}. Guards: {', '.join(NAMES)}.")
        return
    if switch:
        off = set(g.get("off") or [])
        for n in names or NAMES:
            (off.discard if switch == "on" else off.add)(n)
        g["off"] = sorted(off)
        if "cold" in (names or NAMES):
            g.pop("cold_guard", None)   # the old cold-guard switch, replaced by "off"
        save(g)
    if os.environ.get("CC_METRICS_GUARDS") == "0":
        print("All guards are off (CC_METRICS_GUARDS=0 is set in your environment).")
        return
    print("Token-metrics guards. Each one holds once; repeating the same action goes through.")
    for n in NAMES:
        print(f"  {'on ' if is_on(g, n) else 'off'}  {n:<12} {SUMMARY[n]}")
    print("Switch with /token-metrics:guards [name] on|off (no name = all).")


def cold_command(args):
    """`metrics_hook.py guard on|off|status`, run by /token-metrics:cold-guard."""
    if args and args[0] in ("on", "off"):
        command(["cold", args[0]])
        return
    g = load()
    if os.environ.get("CC_METRICS_GUARDS") == "0" or os.environ.get("CC_METRICS_COLD_GUARD") == "0":
        print("Cold-cache guard is off (turned off by an environment variable).")
    elif not is_on(g, "cold"):
        print("Cold-cache guard is off. `/token-metrics:cold-guard on` turns it back on.")
    else:
        print(f"Cold-cache guard is on: it {SUMMARY['cold']}. Sending it again goes through. "
              "`/token-metrics:cold-guard off` turns it off.")
