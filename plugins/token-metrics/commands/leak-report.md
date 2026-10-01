---
description: Rank token leaks by estimated cost (last 30 days)
allowed-tools: Bash
---
!`f=~/.claude/metrics/leak_report.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name leak_report.py 2>/dev/null | head -1); python3 "$f" --days 30 --top 2`

Show the report above exactly as written. Do not add commentary, and do not investigate if it shows an error.
