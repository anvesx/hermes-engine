---
description: Sync your stats now and show your points, rank, badges and card link
argument-hint: "[preview | card --hide spend,name | card --show spend | leave]"
allowed-tools: Bash
---
!`f=~/.claude/metrics/share.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name share.py 2>/dev/null | head -1); if [ -z "$ARGUMENTS" ]; then python3 "$f" sync --force && python3 "$f" me; else python3 "$f" $ARGUMENTS; fi`

Show the output above exactly as written. Do not add commentary, and do not investigate if it shows an error.
