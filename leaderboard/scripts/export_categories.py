"""Prints the plugin's 50 leak categories as JSON for lib/categories.json (npm run categories)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "token-metrics", "scripts"))
import leak_categories  # noqa: E402

print(json.dumps({str(n): {"name": name, "group": group, "review": n in leak_categories.REVIEW}
                  for n, (name, group, _) in leak_categories.CATEGORIES.items()}, indent=1))
