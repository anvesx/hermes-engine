---
description: Export anonymous aggregate token data for the team's token-leak study (no prompts, code, paths or names)
argument-hint: "[preview]"
allowed-tools: Bash
---
!`f=~/.claude/metrics/research.py; [ -f "$f" ] || f=$(find ~/.claude/plugins -path "*token-metrics*" -name research.py 2>/dev/null | head -1); if [ "$ARGUMENTS" = "preview" ]; then python3 "$f" preview; else python3 "$f" export; fi`

Show the output above exactly as written. Do not add commentary, and do not investigate if it shows an error.
