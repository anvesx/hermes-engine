---
description: Join if needed, sync your stats, and open your personal dashboard (usage, points, badges, leaderboard) in the browser
argument-hint: "[nothing: sign in with Google | you@devxlabs.ai | verify <code> <Your Name>]"
allowed-tools: Bash
---
!`f=~/.claude/metrics/share.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name share.py 2>/dev/null | head -1); python3 "$f" dashboard $ARGUMENTS`

Show the output above exactly as written. Do not add commentary, and do not investigate if it shows an error.
