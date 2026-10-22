---
description: Hold the first message after the prompt cache expires in a big chat, once, to show what sending it costs (on / off / status)
argument-hint: "[on | off]"
allowed-tools: Bash
---
!`f=$(find ~/.claude/plugins -path "*token-metrics*" -name metrics_hook.py -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1); if [ -z "$f" ]; then echo "Could not find the token-metrics plugin."; else case "$ARGUMENTS" in on|off) python3 "$f" guard "$ARGUMENTS" ;; *) python3 "$f" guard status ;; esac; fi`

Show the output above exactly as written. Do not add other commentary, and do not investigate if it shows an error.
