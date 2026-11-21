#!/usr/bin/env bash
# Build a small sample repo for the Route B demo: two failing tests (a bug and a missing function) and
# Claude Code wired to the Antigravity MCP server. Usage: ./setup_demo.sh [target dir, default ~/route-b-demo]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/route-b-demo}"
if [ -e "$DEST" ]; then echo "$DEST already exists; remove it or pass another path." >&2; exit 1; fi
mkdir -p "$DEST/textkit" "$DEST/tests" "$DEST/.claude"
cd "$DEST"

cat > textkit/__init__.py <<'EOF'
EOF

cat > textkit/slug.py <<'EOF'
import re


def slugify(text: str) -> str:
    """'Hello, World!' -> 'hello-world'"""
    text = text.lower()
    return re.sub(r"[^a-z0-9]", "-", text)
EOF

cat > textkit/duration.py <<'EOF'
def parse_duration(text: str) -> int:
    """Parse '1h30m', '45s', '2h', '1h5m10s' into seconds. Raise ValueError on anything else."""
    raise NotImplementedError
EOF

cat > tests/__init__.py <<'EOF'
EOF

cat > tests/test_slug.py <<'EOF'
import unittest

from textkit.slug import slugify


class SlugTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation_collapses(self):
        self.assertEqual(slugify("Hello,  World!"), "hello-world")

    def test_edges_trimmed(self):
        self.assertEqual(slugify("  --Ship it--  "), "ship-it")
EOF

cat > tests/test_duration.py <<'EOF'
import unittest

from textkit.duration import parse_duration


class DurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration("45s"), 45)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("1h5m10s"), 3910)

    def test_invalid(self):
        for bad in ("", "abc", "10x", "h1"):
            with self.assertRaises(ValueError):
                parse_duration(bad)
EOF

cat > CLAUDE.md <<'EOF'
# Routing rule (Route B demo)

You are the lead. Keep planning, design decisions and review yourself.

Small, well-specified tasks go to Antigravity through the `antigravity` MCP server:
- bug fixes with a failing test, writing tests, small UI changes, small refactors.
- Call `delegate_task` with a precise `task` (files, expected behaviour), a short `label`, a `category`,
  `acceptance_checks`, and `check_command: "python3 -m unittest -q"`.
- Independent small tasks can be delegated in parallel.
- Review the returned diff yourself. If it is right and the check passed, call `merge_delegation`;
  otherwise `discard_delegation` and either re-delegate with a clearer task or do it yourself.
- Then run `python3 -m unittest -q` in the real tree to confirm.

Anything that needs design choices or wide context stays with you.
EOF

cat > .mcp.json <<EOF
{
  "mcpServers": {
    "antigravity": {
      "command": "python3",
      "args": ["$HERE/antigravity_mcp.py"]
    }
  }
}
EOF

cat > .claude/settings.json <<'EOF'
{
  "enableAllProjectMcpServers": true,
  "permissions": { "allow": ["mcp__antigravity", "Bash(python3 -m unittest:*)"] }
}
EOF

printf '__pycache__/\n' > .gitignore
git init -q
git add -A
git -c user.name=demo -c user.email=demo@example.com commit -qm "Sample repo for the Route B demo"
echo "Demo repo ready: $DEST"
echo "  cd $DEST && python3 -m unittest -q    # 4 failing tests"
echo "  claude    # then: 'Fix the failing tests.'"
