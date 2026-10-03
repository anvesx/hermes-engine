---
description: Join the company token-metrics leaderboard (opt-in; emails you a code)
argument-hint: you@devxlabs.ai  |  verify <code> <Your Name>
allowed-tools: Bash
---
!`f=~/.claude/metrics/share.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name share.py 2>/dev/null | head -1); case "$ARGUMENTS" in verify*) python3 "$f" $ARGUMENTS ;; *) python3 "$f" join $ARGUMENTS ;; esac`

Show the output above exactly as written. Do not add commentary, and do not investigate if it shows an error.
