"""
leak_categories.py - the 50 leak categories the report shows by default.

Each category sums one or more detector findings: core leaks by their id in leak_report.LEAKS,
canvas rows by lid(<canvas row>). Numbers are fixed (ranked by cost when the list was made);
the table still sorts by cost on every run. The full canvas list is still printed with --all.
"""

from leak_extra import lid

GROUP_START = "Starting context and setup"
GROUP_HISTORY = "Conversation history"
GROUP_CACHE = "Prompt cache"
GROUP_AGENTS = "Agents"
GROUP_EXPLORE = "Exploration and file reading"
GROUP_OUTPUT = "Tool and terminal output"
GROUP_IMAGES = "Images and browser"
GROUP_WEB = "Web research"
GROUP_MODEL = "Model and output"
GROUP_RETRY = "Retries and rework"
GROUP_VISIBILITY = "Observability"

# number: (name, group, finding keys summed into the row)
CATEGORIES = {
    1: ("Heavy starting context", GROUP_START, [1]),
    2: ("Cache-write premium", GROUP_CACHE, [lid(37)]),
    3: ("Cold cache at session and agent start", GROUP_CACHE, [lid(22)]),
    4: ("Cache expired after a break", GROUP_CACHE, [26]),
    5: ("Many agents", GROUP_AGENTS, [4]),
    6: ("Long history replay", GROUP_HISTORY, [lid(1)]),
    7: ("Interrupted turns", GROUP_RETRY, [lid(134)]),
    8: ("Sessions that never end", GROUP_HISTORY, [2]),
    9: ("No clear direction", GROUP_EXPLORE, [5]),
    10: ("Restarting too often", GROUP_HISTORY, [lid(10)]),
    11: ("Stale tool results carried forward", GROUP_HISTORY, [lid(5)]),
    12: ("Bigger model than needed", GROUP_MODEL, [6]),
    13: ("Fork context duplication", GROUP_AGENTS, [23]),
    14: ("Large tool-call arguments", GROUP_OUTPUT, [lid(66)]),
    15: ("Agent startup cost", GROUP_AGENTS, [lid(125)]),
    16: ("Model switch rewrote the cache", GROUP_CACHE, [lid(30)]),
    17: ("Old replies replayed", GROUP_HISTORY, [lid(6)]),
    18: ("Clarification loops", GROUP_RETRY, [lid(131)]),
    19: ("Screenshot accumulation", GROUP_IMAGES, [14]),
    20: ("Visual iteration loops", GROUP_IMAGES, [21]),
    21: ("Cache not reused", GROUP_CACHE, [lid(35), lid(21), lid(24)]),
    22: ("Correction churn", GROUP_RETRY, [20]),
    23: ("Agents racing the cache", GROUP_CACHE, [lid(34)]),
    24: ("Too much tool output", GROUP_OUTPUT, [7]),
    25: ("Noisy and repeated terminal output", GROUP_OUTPUT, [17, lid(87), lid(82), lid(84)]),
    26: ("Repeated tasks across sessions", GROUP_HISTORY, [15]),
    27: ("Failed, retried and polling calls", GROUP_RETRY, [16, 9, lid(136)]),
    28: ("Repeated screenshots", GROUP_IMAGES, [lid(114), lid(112), lid(120)]),
    29: ("Progress narration", GROUP_MODEL, [lid(54)]),
    30: ("Whole-file reads", GROUP_EXPLORE, [lid(71)]),
    31: ("Duplicate reading across agents", GROUP_AGENTS, [24, lid(128)]),
    32: ("Agent coordination chatter", GROUP_AGENTS, [lid(126)]),
    33: ("Large images and PDFs", GROUP_IMAGES, [lid(111), lid(115), lid(116), lid(117)]),
    34: ("Broad or unbounded searches", GROUP_EXPLORE, [lid(73), lid(79)]),
    35: ("Bloated JSON and query results", GROUP_OUTPUT, [lid(98), lid(99), lid(100)]),
    36: ("Wordy and repeated output", GROUP_MODEL, [8, lid(52), lid(53), lid(58), lid(60)]),
    37: ("Web pages and search results", GROUP_WEB,
         [lid(101), lid(109), lid(103), lid(105), lid(107), lid(110), lid(104)]),
    38: ("Copied history (pastes, transcripts, forks)", GROUP_HISTORY, [lid(7), lid(8), lid(9)]),
    39: ("Compaction cost", GROUP_HISTORY, [19]),
    40: ("Git and GitHub output", GROUP_OUTPUT, [lid(n) for n in (91, 92, 93, 94, 95, 96)]),
    41: ("Dependency, vendor and generated files", GROUP_EXPLORE, [lid(76), lid(77)]),
    42: ("Verbose agent reports and briefs", GROUP_AGENTS, [25, lid(124)]),
    43: ("Repeated reads of unchanged files", GROUP_EXPLORE, [lid(72)]),
    44: ("Re-learning the codebase", GROUP_EXPLORE, [22]),
    45: ("High effort on trivial turns", GROUP_MODEL, [18]),
    46: ("Tool discovery and skill loading", GROUP_START, [lid(65), lid(69), lid(68)]),
    47: ("Usage while idle", GROUP_RETRY, [10]),
    48: ("MCP tool schema bloat", GROUP_START, [12]),
    49: ("Unused skills/plugins", GROUP_START, [13]),
    50: ("No visibility", GROUP_VISIBILITY, [11]),
}

REVIEW = {2, 3, 5, 6, 15, 17, 18, 26, 29}   # spend to review, not all waste
EXAMPLE_ROWS = 15                            # rows that get a "largest examples" list
