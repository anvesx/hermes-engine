---
description: Company token-metrics leaderboard
argument-hint: "[week | month | all]"
allowed-tools: Bash
---
!`f=~/.claude/metrics/share.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name share.py 2>/dev/null | head -1); python3 "$f" leaderboard --period "${ARGUMENTS:-week}"`

Show the table above exactly as written. Do not add commentary, and do not investigate if it shows an error.
