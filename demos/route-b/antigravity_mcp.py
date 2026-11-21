#!/usr/bin/env python3
"""Route B demo: an MCP server that lets Claude Code hand a small task to Antigravity (Gemini).

Claude stays the lead. When it decides a task is small, it calls `delegate_task`. The server:
  1. creates a throwaway git worktree from HEAD, so Antigravity never touches the developer's tree,
  2. runs the Antigravity CLI headless there (`agy -p ... --output-format json`) on a Gemini model,
  3. runs the acceptance check command, if one was given,
  4. returns Antigravity's summary, the check result, the diff and the token usage.
Claude reviews the diff, then calls `merge_delegation` (apply it to the real tree) or `discard_delegation`.

Every delegation is appended to <metrics dir>/delegations.jsonl, so the Gemini tokens, which never appear in
Claude Code's transcripts, can still be counted (see report.py). Task text is not stored, only a short label.

Standard library only. Speaks MCP over stdio (newline-delimited JSON-RPC 2.0).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

SERVER = {"name": "antigravity", "version": "0.1.0"}
DEFAULT_MODEL = os.environ.get("ROUTE_B_MODEL", "gemini-3.8-flash-medium")
AGY = os.environ.get("ROUTE_B_AGY", shutil.which("agy") or "agy")
AGY_TIMEOUT_S = int(os.environ.get("ROUTE_B_TIMEOUT_S", "600"))
CHECK_TIMEOUT_S = 300
DIFF_LIMIT = 20_000           # characters of diff returned to Claude; the full diff stays in the worktree
WORK_ROOT = Path(os.environ.get("ROUTE_B_WORKTREES", Path.home() / ".cache" / "route-b" / "worktrees"))
METRICS_DIR = Path(os.environ.get("CC_METRICS_DIR", Path.home() / ".claude" / "metrics"))
LOG = METRICS_DIR / "delegations.jsonl"

_out_lock = threading.Lock()

TOOLS = [
    {
        "name": "delegate_task",
        "description": (
            "Hand a SMALL, well-specified coding task (bug fix, tests, small UI change, small refactor) to "
            "Antigravity running a Gemini model. It works in an isolated git worktree from HEAD (uncommitted "
            "changes are not included), runs the check command, and returns its summary, the check result, the "
            "diff and token usage. Nothing touches the working tree until you call merge_delegation. Review the "
            "diff before merging. Do not use for tasks that need design decisions or broad context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What to do: files, expected behaviour, constraints."},
                "label": {"type": "string", "description": "Short label for the report, e.g. 'fix slugify dashes'."},
                "category": {"type": "string", "description": "Task type: bugfix, tests, ui, refactor, other."},
                "acceptance_checks": {"type": "array", "items": {"type": "string"},
                                      "description": "Concrete conditions the change must meet."},
                "check_command": {"type": "string",
                                  "description": "Shell command that must pass, e.g. 'python3 -m unittest -q'."},
                "model": {"type": "string", "description": f"Antigravity model id (default {DEFAULT_MODEL})."},
            },
            "required": ["task", "label"],
        },
    },
    {
        "name": "merge_delegation",
        "description": "Apply a delegation's diff to the real working tree, then remove its worktree.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "discard_delegation",
        "description": "Throw a delegation's work away and remove its worktree.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
]


# ------------------------------------------------------------------ helpers

def run(cmd, cwd, timeout=120, shell=False):
    p = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def repo_root():
    start = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    code, out, err = run(["git", "rev-parse", "--show-toplevel"], start)
    if code:
        raise RuntimeError(f"not a git repository: {start}")
    return Path(out.strip())


def log_event(rec):
    try:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def worktree_path(did):
    return WORK_ROOT / did


def staged_diff(wt):
    run(["git", "add", "-A"], wt)
    _, diff, _ = run(["git", "diff", "--cached", "HEAD"], wt)
    _, stat, _ = run(["git", "diff", "--cached", "HEAD", "--numstat"], wt)
    added = removed = files = 0
    for line in stat.splitlines():
        a, r, _name = (line.split("\t") + ["", ""])[:3]
        files += 1
        added += int(a) if a.isdigit() else 0
        removed += int(r) if r.isdigit() else 0
    return diff, files, added, removed


def build_prompt(task, checks, check_command):
    lines = [
        "You are implementing a small, well-defined task handed over by the lead engineer.",
        "Work only inside this repository (the current directory). Make the smallest change that does the task.",
        "Do not commit, do not create branches, do not touch unrelated files.",
        "",
        "TASK:",
        task.strip(),
    ]
    if checks:
        lines += ["", "ACCEPTANCE CHECKS (all must hold):"] + [f"- {c}" for c in checks]
    if check_command:
        lines += ["", f"Run `{check_command}` and make it pass before you finish."]
    lines += ["", "When done, reply with a short summary: the files you changed and what you did."]
    return "\n".join(lines)


# ------------------------------------------------------------------ tools

def delegate_task(args):
    task = args["task"]
    label = args.get("label") or "task"
    model = args.get("model") or DEFAULT_MODEL
    check_command = args.get("check_command") or ""
    root = repo_root()
    did = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    wt = worktree_path(did)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    code, _, err = run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], root)
    if code:
        raise RuntimeError(f"git worktree add failed: {err.strip()}")

    started = time.time()
    cmd = [AGY, "-p", build_prompt(task, args.get("acceptance_checks") or [], check_command),
           "--output-format", "json", "--model", model, "--dangerously-skip-permissions",
           "--print-timeout", f"{AGY_TIMEOUT_S}s"]
    try:
        code, out, err = run(cmd, wt, timeout=AGY_TIMEOUT_S + 60)
    except subprocess.TimeoutExpired:
        code, out, err = 124, "", f"agy timed out after {AGY_TIMEOUT_S}s"
    try:
        res = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except (json.JSONDecodeError, IndexError):
        res = {"response": out[-4000:]}
    # agy can report status ERROR for background noise (telemetry, sign-in for plugins) after finishing the
    # task, so judge by exit code + a response; the check command below is the real test.
    agy_status = res.get("status") or "?"
    status = "done" if code == 0 and res.get("response") else "failed"
    usage = res.get("usage") or {}

    check = None
    if check_command:
        try:
            c, o, e = run(check_command, wt, timeout=CHECK_TIMEOUT_S, shell=True)
            check = {"command": check_command, "passed": c == 0, "output": (o + e)[-2500:]}
        except subprocess.TimeoutExpired:
            check = {"command": check_command, "passed": False, "output": "timed out"}

    diff, files, added, removed = staged_diff(wt)
    seconds = round(time.time() - started, 1)
    log_event({
        "event": "delegated", "id": did, "ts": int(started), "label": label[:80],
        "category": args.get("category") or "other", "model": model, "status": status, "agy_status": agy_status,
        "seconds": seconds, "usage": usage, "checks_passed": None if check is None else check["passed"],
        "files": files, "added": added, "removed": removed,
    })

    parts = [
        f"Delegation {did}: {status} on {model} in {seconds}s (agy status {agy_status}).",
        f"Tokens: {usage.get('input_tokens', '?')} in, {usage.get('output_tokens', '?')} out, "
        f"{usage.get('thinking_tokens', 0)} thinking, {usage.get('cache_read_tokens', 0)} cache read.",
        f"Changed {files} file(s), +{added} -{removed}.",
    ]
    if check:
        parts.append(f"Check `{check['command']}`: {'PASSED' if check['passed'] else 'FAILED'}\n{check['output']}")
    if code and not res.get("response"):
        parts.append(f"agy exited {code}: {err.strip()[-1500:]}")
    parts.append("Antigravity's summary:\n" + (res.get("response") or "(none)").strip())
    shown = diff if len(diff) <= DIFF_LIMIT else diff[:DIFF_LIMIT] + f"\n... diff truncated, full diff in {wt}"
    parts.append("Diff:\n" + (shown or "(no changes)"))
    parts.append(f"Next: review the diff, then merge_delegation(id='{did}') or discard_delegation(id='{did}').")
    return "\n\n".join(parts), status != "done" or (check is not None and not check["passed"])


def remove_worktree(root, wt):
    run(["git", "worktree", "remove", "--force", str(wt)], root)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    run(["git", "worktree", "prune"], root)


def merge_delegation(args):
    did = args["id"]
    root, wt = repo_root(), worktree_path(did)
    if not wt.exists():
        raise RuntimeError(f"no delegation {did}")
    diff, files, _, _ = staged_diff(wt)
    if not diff:
        remove_worktree(root, wt)
        return f"Delegation {did} had no changes; worktree removed.", False
    p = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=root, input=diff + "\n",
                       capture_output=True, text=True)
    if p.returncode:
        return (f"git apply failed (the tree changed since the delegation started?): {p.stderr.strip()}\n"
                f"Worktree kept at {wt}."), True
    remove_worktree(root, wt)
    log_event({"event": "merged", "id": did, "ts": int(time.time())})
    return f"Applied delegation {did} ({files} file(s)) to {root}. Not committed.", False


def discard_delegation(args):
    did = args["id"]
    root, wt = repo_root(), worktree_path(did)
    if wt.exists():
        remove_worktree(root, wt)
    log_event({"event": "discarded", "id": did, "ts": int(time.time())})
    return f"Discarded delegation {did}.", False


HANDLERS = {"delegate_task": delegate_task, "merge_delegation": merge_delegation,
            "discard_delegation": discard_delegation}


# ------------------------------------------------------------------ MCP over stdio

def send(msg):
    with _out_lock:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def call_tool(mid, params):
    name, args = params.get("name"), params.get("arguments") or {}
    try:
        if name not in HANDLERS:
            raise RuntimeError(f"unknown tool {name}")
        text, is_error = HANDLERS[name](args)
    except Exception as e:   # report to Claude instead of crashing the server
        text, is_error = f"{type(e).__name__}: {e}", True
    send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if mid is None:          # notification (initialized, cancelled, ...)
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": SERVER}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            threading.Thread(target=call_tool, args=(mid, params), daemon=True).start()
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})


if __name__ == "__main__":
    main()
