---
description: Show the prompt cache countdown, chat size and cost in your status line (on / keep / replace / off)
argument-hint: "[keep | replace | off]"
allowed-tools: Bash
---
!`f=$(find ~/.claude/plugins -path "*token-metrics*" -name statusline.py -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1); [ -n "$f" ] || f=~/.claude/metrics/statusline.py; case "$ARGUMENTS" in off) python3 "$f" off ;; keep|replace) python3 "$f" install "$ARGUMENTS" ;; *) python3 "$f" install ;; esac`

Show the output above exactly as written. If it says the user already has a status line and asks them to choose, ask which they want (keep theirs and show the cache line below it, or replace it) and then run `/token-metrics:statusline keep` or `/token-metrics:statusline replace` for them. Do not add other commentary, and do not investigate if it shows an error.
