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
"""
import json
import os
import re
import subprocess
import sys
import time

LOG_DIR = os.path.expanduser(os.environ.get("CC_METRICS_DIR", "~/.claude/metrics"))
KEEP_PROMPTS = os.environ.get("CC_METRICS_KEEP_PROMPTS") == "1"   # off by default for privacy
SYNC_EVERY_S = 60 * 60   # same throttle as share.py, checked here so most sessions spawn nothing

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
    for name in ("analyze.py", "leak_report.py", "leak_extra.py", "leak_categories.py", "stats.py", "share.py"):
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
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
