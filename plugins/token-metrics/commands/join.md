---
description: Join the company token-metrics leaderboard with your git email and name (opt-in)
argument-hint: "[you@devxlabs.ai]"
allowed-tools: Bash
---
!`f=~/.claude/metrics/share.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name share.py 2>/dev/null | head -1); python3 "$f" join $ARGUMENTS`

Show the output above exactly as written. Do not add commentary, and do not investigate if it shows an error.
