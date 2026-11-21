#!/bin/bash
# Install or update the token-metrics Claude Code plugin, and put a `token-metrics` command on your PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/anvesx/hermes-engine/main/install.sh | bash
#
# Run it again (or `token-metrics update`) to get the latest version. It:
#   1. adds this repo as the Claude Code plugin marketplace "hermes-engine" (replacing a zip/folder copy of that name)
#   2. installs or updates token-metrics@hermes-engine, and uninstalls copies installed from older zip marketplaces,
#      so only one copy of the hook records events
#   3. refreshes the report scripts in ~/.claude/metrics, which the slash commands run
#   4. installs the `token-metrics` command into ~/.local/bin (adding it to PATH in ~/.zshrc if needed)
# Your data in ~/.claude/metrics is never touched.
#
# Testing: TOKEN_METRICS_SOURCE=<repo path or owner/repo> and TOKEN_METRICS_BIN=<dir> override the source and the
# command's directory; CLAUDE_CONFIG_DIR and CC_METRICS_DIR are honoured as usual.

main() {
  set -euo pipefail
  local source="${TOKEN_METRICS_SOURCE:-anvesx/hermes-engine}"
  local market="hermes-engine" plugin="token-metrics@hermes-engine"
  say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
  die() { printf 'token-metrics install: %s\n' "$*" >&2; exit 1; }

  [ "$(uname)" = "Darwin" ] || say "Note: written for macOS; continuing anyway."
  command -v claude >/dev/null 2>&1 || die "Claude Code is not installed (no \`claude\` command). Install it first: https://claude.com/claude-code"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' </dev/null >/dev/null 2>&1 \
    || die "Python 3.8+ is needed. On macOS run: xcode-select --install"

  # 1. marketplace
  local state
  state=$(claude plugin marketplace list --json </dev/null 2>/dev/null | python3 -c '
import json, os, sys
src = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
m = next((r for r in rows if isinstance(r, dict) and r.get("name") == "hermes-engine"), None)
if m is None:
    print("missing")
elif (m.get("repo") or "").lower() == src.lower() or os.path.realpath(m.get("path") or "/nonexistent") == os.path.realpath(src):
    print("ok")
else:
    print("other")' "$source")
  case "$state" in
    ok)    say "Updating the hermes-engine marketplace"; claude plugin marketplace update "$market" </dev/null ;;
    other) say "Replacing the old hermes-engine marketplace (zip or folder copy) with $source"
           claude plugin marketplace remove "$market" </dev/null || true
           claude plugin marketplace add "$source" </dev/null ;;
    *)     say "Adding the hermes-engine marketplace ($source)"; claude plugin marketplace add "$source" </dev/null ;;
  esac

  # 2. plugin: remove copies from other marketplaces, then install or update ours
  local installed id
  installed=$(claude plugin list --json </dev/null 2>/dev/null | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    rows = []
rows = rows if isinstance(rows, list) else rows.get("plugins", [])
for r in rows:
    if isinstance(r, dict) and str(r.get("id", "")).startswith("token-metrics@"):
        print(r["id"])')
  for id in $installed; do
    if [ "$id" != "$plugin" ]; then
      say "Uninstalling an older copy: $id (your data in ~/.claude/metrics is kept)"
      claude plugin uninstall "$id" --keep-data </dev/null || true
    fi
  done
  if printf '%s\n' $installed | grep -qx "$plugin"; then
    say "Updating $plugin"
    claude plugin update "$plugin" </dev/null
  else
    say "Installing $plugin"
    claude plugin install "$plugin" --scope user </dev/null
  fi
  claude plugin enable "$plugin" </dev/null >/dev/null 2>&1 || true

  # 3. where it landed; refresh the scripts the slash commands run
  local dir
  dir=$(claude plugin list --json </dev/null 2>/dev/null | python3 -c '
import json, sys
rows = json.load(sys.stdin)
rows = rows if isinstance(rows, list) else rows.get("plugins", [])
print(next((r.get("installPath", "") for r in rows if isinstance(r, dict) and r.get("id") == sys.argv[1]), ""))' "$plugin")
  [ -n "$dir" ] && [ -d "$dir/scripts" ] || die "the plugin did not install (claude plugin list does not show $plugin)"
  python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import metrics_hook; metrics_hook.sync_report_scripts()' "$dir/scripts" </dev/null

  # 4. the terminal command
  local bin="${TOKEN_METRICS_BIN:-$HOME/.local/bin}"
  mkdir -p "$bin"
  cp "$dir/bin/token-metrics" "$bin/token-metrics"
  chmod +x "$bin/token-metrics"
  local on_path=1
  case ":$PATH:" in *":$bin:"*) ;; *) on_path=0 ;; esac
  if [ "$on_path" = 0 ] && [ -z "${TOKEN_METRICS_BIN:-}" ]; then
    local rc="$HOME/.zshrc"
    if ! grep -qs 'token-metrics: ~/.local/bin' "$rc"; then
      printf '\n# token-metrics: ~/.local/bin on PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
      say "Added ~/.local/bin to PATH in ~/.zshrc"
    fi
  fi

  local version
  version=$(basename "$dir")
  printf '\n'
  say "token-metrics $version is installed."
  printf '    In Claude Code: restart it, or run /reload-plugins, then /token-metrics:leak-report\n'
  printf '    In a terminal:  token-metrics report   (token-metrics help lists everything)\n'
  [ "$on_path" = 1 ] || printf '    Open a new terminal first (or run: export PATH="%s:$PATH")\n' "$bin"
  printf '    To update later: token-metrics update\n'
}

main "$@"
