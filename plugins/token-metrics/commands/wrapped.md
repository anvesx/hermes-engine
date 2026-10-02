---
description: Your Claude Code usage in numbers - tokens, spend, active hours, streaks (local only)
allowed-tools: Bash
---
!`f=~/.claude/metrics/stats.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name stats.py 2>/dev/null | head -1); python3 "$f"`

Show the summary above exactly as written. Do not add commentary, and do not investigate if it shows an error.
