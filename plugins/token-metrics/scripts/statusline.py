#!/usr/bin/env python3
"""
statusline.py - prompt cache countdown and chat size for the Claude Code status line.

Prices come from leak_report.py. The hook keeps this script and leak_report.py up to date in
~/.claude/metrics, a path that survives plugin updates. A plugin can't set the main status line, so
`/token-metrics:statusline` adds it to the user's ~/.claude/settings.json, with a backup.

  python3 statusline.py install            add it; refuses if another status line is set
  python3 statusline.py install --keep     keep the existing status line and show ours below it
  python3 statusline.py install --replace  replace the existing one (saved, so `off` restores it)
  python3 statusline.py off                remove ours and restore what was there before

Run with no arguments, it is the status line itself: it reads Claude Code's status line JSON on stdin
and prints one right-aligned line from `prompt_cache` (Claude Code 2.1.251+; miss cause 2.1.260+):
  warm   cache ● 1h ████░░ 37m left · hit 91% · chat 152k · re-read $0.03 · if cold $1.22
  cold   cache ○ cold · chat 152k · next msg re-caches ≈ $1.22 · new task? /clear
Costs are API list prices. On a subscription they show the relative weight against usage limits.
It must never break the status line: any error prints nothing.
"""
import json
import os
import shutil
import subprocess
import sys
import time

LOG_DIR = os.path.expanduser(os.environ.get("CC_METRICS_DIR", "~/.claude/metrics"))
SETTINGS = os.path.expanduser("~/.claude/settings.json")
STATE = os.path.join(LOG_DIR, "statusline.json")   # the status line we replaced or wrapped, for `off`
MANAGED = (os.path.expanduser("~/.claude/remote-settings.json"),
           "/Library/Application Support/ClaudeCode/managed-settings.json",
           "/etc/claude-code/managed-settings.json")
REFRESH_S = 30            # re-run on a timer so the countdown moves while idle

GREEN, YELLOW, RED, DIM, WHITE, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[97m", "\033[0m"
BAR = 6
MARGIN = 6                # room for Claude Code's own padding, so the line never wraps
BIG_CHAT = 300_000        # chat size where every message gets expensive: suggest /compact at a break
CHAT_COLORS = ((600_000, RED), (500_000, YELLOW), (300_000, WHITE))   # below 300k: dim
HIT_LOW = 0.80            # session hit rate shown in yellow below this (our choice; Claude Code defines none)
WRITE_MULT = {"5m": 1.25, "1h": 2.0}   # cache-write price / input price, as in leak_report.WRITE_MULT
WRAP_TIMEOUT_S = 5


def prices(model):
    """(input, output, cache read) $/M from leak_report's PRICES, or None if it can't be loaded."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import leak_report
        return leak_report.price(model)
    except Exception:
        return None


def usd(x):
    return f"${x:.2f}" if x >= 0.01 else "<$0.01"


def k(n):
    return f"{round(n / 1000)}k" if n >= 1000 else str(n)


def left_text(s):
    if s < 60:
        return f"{int(s)}s left"
    if s < 3600:
        return f"{int(s // 60)}m left"
    return f"{int(s // 3600)}h {int(s % 3600 // 60)}m left"


def chat_color(n):
    return next((c for limit, c in CHAT_COLORS if n >= limit), DIM)


def line(*segments):
    """(text, color) segments joined and right-aligned to the COLUMNS width Claude Code sets."""
    try:
        cols = int(os.environ.get("COLUMNS", "0"))
    except ValueError:
        cols = 0
    text = " · ".join(t for t, _ in segments)
    pad = max(0, cols - len(text) - MARGIN)
    body = f"{DIM} · {RESET}".join(f"{c}{t}{RESET}" for t, c in segments)
    # Claude Code trims leading spaces, so pad with no-break spaces after a reset code
    return RESET + "\u00a0" * pad + body


def cache_line(data):
    pc = data.get("prompt_cache")
    if not pc:
        return line(("cache · waiting for first reply", DIM))
    if pc.get("caching_observed") is False:
        return line(("cache · off", DIM))

    ttl = pc.get("ttl")
    n = pc.get("recache_tokens_if_cold") or (data.get("context_window") or {}).get("total_input_tokens")
    p = prices((data.get("model") or {}).get("id"))
    cold_cost = warm_cost = None
    if n and p:
        cold_cost = n * p[0] * WRITE_MULT.get(ttl, 2.0) / 1e6   # history re-written to the cache
        warm_cost = n * p[2] / 1e6                              # same history read from the cache
    ttl_s = {"5m": 300, "1h": 3600}.get(ttl)
    exp = pc.get("expires_at")
    left = (exp - time.time()) if exp else None
    big = bool(n and n >= BIG_CHAT)
    chat = (f"chat {k(n)}", chat_color(n)) if n else None
    hr = pc.get("hit_ratio")
    hit = (f"hit {round(hr * 100)}%", YELLOW if hr < HIT_LOW else DIM) if hr is not None else None

    if pc.get("warm") and left is not None and left > 0:
        head = "cache ●" + (f" {ttl}" if ttl else "")
        if ttl_s:
            filled = round(max(0.0, min(1.0, left / ttl_s)) * BAR)
            head += " " + "█" * filled + "░" * (BAR - filled)
        segs = [(head + " " + left_text(left), YELLOW if ttl_s and left / ttl_s < 0.2 else GREEN)]
        if hit:
            segs.append(hit)
        if pc.get("misses"):
            segs.append((f"misses {pc['misses']}", YELLOW))
        if chat:
            segs.append(chat)
        if cold_cost is not None:
            segs.append((f"re-read {usd(warm_cost)} · if cold {usd(cold_cost)}", DIM))
        if big:
            segs.append(("/compact at next break", YELLOW))
        return line(*segs)

    segs = [("cache ○ cold", RED)]
    if chat:
        segs.append(chat)
    if cold_cost is not None:
        segs.append((f"next msg re-caches ≈ {usd(cold_cost)}", RED))
    cause = (pc.get("last_miss_cause") or {}).get("causes")
    if cause:
        segs.append(("last miss: " + ", ".join(cause), DIM))
    segs.append(("new task? /clear" + (" · same task? /compact" if big else ""), YELLOW))
    return line(*segs)


def wrapped_output(raw):
    """Output of the status line the user had before, when installed with --keep."""
    try:
        with open(STATE) as f:
            state = json.load(f)
        prev = state.get("previous") or {}
        if state.get("mode") != "keep" or not prev.get("command"):
            return ""
        r = subprocess.run(prev["command"], shell=True, input=raw, capture_output=True, text=True,
                           timeout=WRAP_TIMEOUT_S)
        return r.stdout.rstrip("\n")
    except Exception:
        return ""


def render():
    raw = sys.stdin.read()
    before = wrapped_output(raw)
    if before:
        print(before)
    try:
        print(cache_line(json.loads(raw)))
    except Exception:
        pass


# ---- install / off ----

def our_command():
    return f'python3 "{os.path.join(LOG_DIR, "statusline.py")}"'


def is_ours(sl):
    return isinstance(sl, dict) and "statusline.py" in str(sl.get("command", "")) and LOG_DIR in str(sl["command"])


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_settings(settings):
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, SETTINGS + ".bak-token-metrics")
    tmp = SETTINGS + ".tmp-token-metrics"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)   # leave the user's other text as written
        f.write("\n")
    os.replace(tmp, SETTINGS)


def managed_status_line():
    for path in MANAGED:
        try:
            if json.load(open(path)).get("statusLine"):
                return path
        except Exception:
            continue
    return None


def install(mode):
    os.makedirs(LOG_DIR, exist_ok=True)
    here = os.path.dirname(os.path.abspath(__file__))
    if here != os.path.abspath(LOG_DIR):   # the hook does this at session start; do it now so it works right away
        try:
            sys.path.insert(0, here)
            import metrics_hook
            metrics_hook.sync_report_scripts()
        except Exception:
            shutil.copy2(os.path.abspath(__file__), os.path.join(LOG_DIR, "statusline.py"))
    try:
        settings = load_settings()
    except json.JSONDecodeError:
        print(f"Could not read {SETTINGS} (invalid JSON). Nothing was changed.")
        return 1
    current = settings.get("statusLine")
    if is_ours(current):
        try:
            with open(STATE) as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        if mode and state.get("previous") and state.get("mode") != mode:
            state["mode"] = mode
            with open(STATE, "w") as f:
                json.dump(state, f, indent=2)
            print("Switched to " + ("keep: your previous status line is shown above the cache line." if mode == "keep"
                                    else "replace: only the cache line shows (`off` restores yours)."))
            return 0
        print("The token-metrics status line is already on. Its script is refreshed to this plugin version.")
        return 0
    if current and mode is None:
        print("You already have a status line:\n  " + str(current.get("command", current)) + "\n"
              "Choose one and run the command again with it:\n"
              "  keep     keep yours and show the cache line below it\n"
              "  replace  use only the cache line (yours is saved; `off` restores it)\n"
              "Nothing was changed.")
        return 2
    if current:
        with open(STATE, "w") as f:
            json.dump({"mode": mode, "previous": current}, f, indent=2)
    settings["statusLine"] = {"type": "command", "command": our_command(), "refreshInterval": REFRESH_S}
    save_settings(settings)
    print("Status line on: prompt cache countdown, chat size and cost. It appears after Claude's next reply.")
    if current:
        print("Your previous status line is " + ("shown above it." if mode == "keep" else "saved; `off` restores it."))
    print(f"Backup of your settings: {SETTINGS}.bak-token-metrics")
    managed = managed_status_line()
    if managed:
        print(f"Warning: your organisation's managed settings ({managed}) set their own status line, which "
              "overrides yours. Ask the admin to remove it, or this line won't show.")
    return 0


def off():
    try:
        settings = load_settings()
    except json.JSONDecodeError:
        print(f"Could not read {SETTINGS} (invalid JSON). Nothing was changed.")
        return 1
    if not is_ours(settings.get("statusLine")):
        print("The token-metrics status line is not on. Nothing was changed.")
        return 0
    try:
        prev = json.load(open(STATE)).get("previous")
    except Exception:
        prev = None
    if prev:
        settings["statusLine"] = prev
    else:
        settings.pop("statusLine", None)
    save_settings(settings)
    try:
        os.remove(STATE)
    except OSError:
        pass
    print("Status line off." + (" Your previous status line is back." if prev else ""))
    return 0


def main(argv):
    if not argv:
        render()
        return 0
    if argv[0] == "install":
        mode = "keep" if "--keep" in argv or "keep" in argv[1:] else \
               "replace" if "--replace" in argv or "replace" in argv[1:] else None
        return install(mode)
    if argv[0] == "off":
        return off()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
