---
description: Show or switch the guards that stop token leaks as they happen (big file reads, forks, new tasks in old chats, long chats, cold cache)
argument-hint: "[name] [on | off]"
allowed-tools: Bash
---
!`f=$(find ~/.claude/plugins -path "*token-metrics*" -name metrics_hook.py -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1); if [ -z "$f" ]; then echo "Could not find the token-metrics plugin."; else python3 "$f" guards $ARGUMENTS; fi`

Show the output above exactly as written. Do not add other commentary, and do not investigate if it shows an error.
