#!/usr/bin/env python3
"""
leak_extra.py - the "Additional categories" section of the team's Leak Categories canvas.

leak_report.py ranks the core leaks (1-22, 4a-4c) and imports this module for the canvas's
other 109 categories, labelled A<n> with their canvas row number. Each one is either
  measured       detected from transcripts by analyse() or cross_session() below, including the
                 attachments Claude Code records (instructions, skill listings, prompt snapshots)
  same as #x     the same signal as a core leak, shown once there (SAME_AS)
  unmeasurable   needs data transcripts don't have; reported with the reason instead of $0.00

Costs use the same model as leak_report.py: a leaked item is charged for every later call
that re-reads it, at the cache-read price, until the next compaction.
"""
import bisect
import hashlib
import json
import os
import re
from collections import defaultdict

HISTORY_LIMIT = 100_000        # conversation history per call considered reasonable
STALE_CALLS = 30               # a tool result still carried this many calls later counts as stale
PASTE_MIN = 400                # pasted paragraph size (chars) worth tracking for repeats
TRANSCRIPT_MIN = 2_000         # prompt size before a pasted chat transcript counts
RESTART_GAP = 60 * 60          # a session starting this soon after the previous one is a restart
UNCACHED_MIN = 10_000          # uncached input on one call before it counts as missing caching
CONCURRENT_S = 10              # helper agents starting this close together race the cache
PLAN_LIMIT = 5                 # plan/todo updates per task considered reasonable
ECHO_SIM = 0.7                 # word overlap between a reply's first sentence and the prompt
NARRATION_KEEP = 50            # text per tool-calling message considered reasonable
CODE_MIN = 300                 # code block size (chars) worth tracking for reprints
DISCOVERY_LIMIT = 2            # tool-discovery calls per session considered reasonable
ARGS_BIG = 1_000               # tool-call arguments this large count as oversized
WHOLE_FILE = 5_000             # an unsliced Read this large counts as a whole-file read
SEARCH_LINES = 100             # search result lines considered reasonable
BIG, KEEP = 4_000, 2_000       # oversized result size, and the part charged as useful
DUP_LINE_SHARE = 0.5           # share of repeated lines in a log-like result
SEARCH_RESULTS = 10            # search results (distinct URLs) considered reasonable
IMAGE_BIG, IMAGE_KEEP = 1_200, 800
BRIEF_BIG = 1_000              # agent brief size considered reasonable
POLL_MIN = 3                   # identical calls with identical results before it is polling
START_BASELINE = 10_000
DUP_LINE_MIN = 30              # instruction line length (chars) worth checking for duplicates
GUIDANCE_KEEP = 2_000          # always-loaded project guidance (tokens) considered reasonable
EXAMPLE_KEEP = 2               # few-shot examples per tool, prompt or instruction file considered reasonable
INJECT_KEEP = 300              # injected MCP-server or hook context per block (tokens) considered reasonable
SKILL_BIG, SKILL_KEEP = 3_000, 1_500   # invoked skill body size, and the part charged as useful
DUP_SOURCE = 0.5               # share of a web result already seen in another source
SHINGLE = 8                    # words per shingle when comparing web sources
UNCHANGED_SHARE = 0.8          # share of a repeated run's tool results identical to the earlier run

EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
PLAN_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate"}
DISCOVERY_TOOLS = {"ToolSearch", "ListMcpResourcesTool"}
DEP_DIRS = re.compile(r"(^|/)(node_modules|\.venv|venv|dist|build|target|\.next|vendor|__pycache__)/")
GENERATED = re.compile(r"(\.lock$|-lock\.json$|\.min\.(js|css)$|\.map$|\.pbxproj$|\.g\.dart$|\.pb\.go$|_pb2\.py$|"
                       r"(^|/)(dist|build|out|\.next|generated|__generated__)/)")
LINT_CMD = re.compile(r"\b(eslint|ruff|flake8|pylint|tsc|mypy|swiftlint|golangci-lint|rubocop|stylelint|biome|lint)\b")
TRACEBACK = re.compile(r"(Traceback \(most recent call last\)|^\s+at .+:\d+:\d+\)?$|Exception in thread|^panic:)", re.M)
DIFF_CMD = re.compile(r"\bgit\s+(diff|show)\b")
LOG_CMD = re.compile(r"\bgit\s+log\b")
LOG_SHORT = re.compile(r"--oneline|--format|--pretty")
STATUS_CMD = re.compile(r"\bgit\s+status\b")
PR_CMD = re.compile(r"\bgh\s+(pr\s+view\b.*--comments|api\b.*(pulls|comments))")
ISSUE_CMD = re.compile(r"\bgh\s+issue\s+view\b")
DB_CMD = re.compile(r"\b(psql|mysql|sqlite3|mongosh|bq\s+query|clickhouse-client)\b")
SEARCH_CMD = re.compile(r"(^|\|\s*|&&\s*)(grep|rg|ag|find)\b")
URL_RE = re.compile(r"https?://[^\s)\]\"'>]+")
TRANSCRIPT_MARK = re.compile(r"^\s*(Human|User|Assistant|Claude|⏺)\s*[:>]?\s", re.M)
EXAMPLE_RE = re.compile(r"<example[^>]*>.*?</example>", re.S)
MEMORY_LINK = re.compile(r"\]\(([^)\s]+\.md)\)")
PDF_TEXT_CMD = re.compile(r"\b(pdftotext|pdfplumber|pypdf|PyPDF2|fitz|pymupdf|pdfminer|textutil)\b")
OCR_CMD = re.compile(r"\b(tesseract|ocrmypdf|easyocr)\b|\bocr\b", re.I)
DOC_NAME = re.compile(r"[\w.\-]+\.(?:pdf|png|jpe?g)\b", re.I)
COORDINATION = ("<cross-session-message", "<teammate-message", "<task-notification")

PAYLOAD = "needs the exact request body (cache_control breakpoints, edited messages), which transcripts don't record"
LABEL = "needs a labelled review of what was relevant or necessary"
EXPERIMENT = "needs matched runs with independent acceptance checks"
CONFIG = "depends on settings or provider scope that transcripts don't record"
HIDDEN = "these model calls are not recorded in transcripts"

# canvas row: (name, canvas category, reason it is unmeasurable, or None when measured here)
ADDITIONAL = {
    1: ("Long single-thread history replay", "Conversation history", None),
    3: ("Obsolete requirements retained in context", "Conversation history", LABEL),
    4: ("Abandoned approaches retained in context", "Conversation history", LABEL),
    5: ("Old tool results carried into later turns", "Conversation history", None),
    6: ("Previous assistant answers repeatedly replayed", "Conversation history", None),
    7: ("Repeatedly pasted background information", "Conversation history", None),
    8: ("Full transcripts copied between chats", "Conversation history", None),
    9: ("Conversation forks duplicating history", "Conversation history", None),
    10: ("Rebuilding context after frequent fresh starts", "Conversation history", None),
    14: ("Overlapping directory-level instructions", "Persistent instructions and memory", None),
    16: ("Duplicate rules across instruction layers", "Persistent instructions and memory", None),
    17: ("Irrelevant always-loaded project guidance", "Persistent instructions and memory", None),
    18: ("Stale auto-memory entries", "Persistent instructions and memory", None),
    19: ("Excessive few-shot examples", "Persistent instructions and memory", None),
    20: ("Conflicting instructions causing corrective turns", "Persistent instructions and memory",
         LABEL + " (all corrections are counted in #20)"),
    21: ("Missing prompt caching where supported", "Cache misses and invalidation", None),
    22: ("Cold-cache requests", "Cache misses and invalidation", None),
    24: ("Prefixes below cache eligibility thresholds", "Cache misses and invalidation", None),
    25: ("Timestamps inside otherwise stable prefixes", "Cache misses and invalidation", None),
    26: ("Changing system-prompt content", "Cache misses and invalidation", None),
    27: ("Changing loaded tool definitions", "Cache misses and invalidation", None),
    28: ("Editing earlier conversation messages", "Cache misses and invalidation", PAYLOAD),
    29: ("Unstable tool serialization or ordering", "Cache misses and invalidation", None),
    30: ("Switching models with no reusable cache on the receiving model", "Cache misses and invalidation", None),
    31: ("Cache breakpoints on changing content", "Cache overhead and configuration", PAYLOAD),
    32: ("Stable content outside cached prefixes", "Cache overhead and configuration", PAYLOAD),
    33: ("Cache breakpoint lookback limits", "Cache overhead and configuration", PAYLOAD),
    34: ("Concurrent requests before cache creation completes", "Cache overhead and configuration", None),
    35: ("Cache writes never reused", "Cache overhead and configuration", None),
    36: ("Repeated cache warmup requests", "Cache overhead and configuration", HIDDEN),
    37: ("Cache-write pricing premiums", "Cache overhead and configuration", None),
    38: ("Thinking or effort changes invalidating cached context", "Cache overhead and configuration", None),
    39: ("Tool-choice or web-tool configuration changes", "Cache overhead and configuration",
         CONFIG + " (tool_choice; web tools added or removed are counted in A27)"),
    40: ("Cache isolation across providers or workspaces", "Cache overhead and configuration", None),
    42: ("Excessive extended-thinking generation", "Model selection and reasoning", EXPERIMENT),
    43: ("Replayed thinking blocks where preserved", "Model selection and reasoning",
         "transcripts record thinking blocks, but not whether later requests kept them (depends on the model)"),
    44: ("Repeated reasoning over unchanged evidence", "Model selection and reasoning", LABEL),
    45: ("Replanning after every minor update", "Model selection and reasoning", None),
    46: ("Generating unnecessary alternative approaches", "Model selection and reasoning", LABEL),
    47: ("Repeated self-critique cycles", "Model selection and reasoning", LABEL),
    48: ("Model handoffs requiring context reconstruction", "Model selection and reasoning",
         LABEL + " (the cache rewrite is counted in A30)"),
    49: ("Switching models followed by duplicate task execution", "Model selection and reasoning", EXPERIMENT),
    50: ("Tokenizer differences between model versions", "Model selection and reasoning",
         "needs the same payload counted on both models"),
    52: ("Repeating the user's question", "Answer and artifact generation", None),
    53: ("Repeating already-established explanations", "Answer and artifact generation", None),
    54: ("Unnecessary progress narration", "Answer and artifact generation", None),
    55: ("Excessive examples", "Answer and artifact generation", LABEL),
    56: ("Multiple unsolicited solution variants", "Answer and artifact generation", LABEL),
    58: ("Reprinting previously generated artifacts", "Answer and artifact generation", None),
    59: ("Duplicating information across output formats", "Answer and artifact generation", LABEL),
    60: ("Truncated answers requiring regeneration", "Answer and artifact generation", None),
    65: ("Unnecessary tool discovery calls", "Tools, MCP, skills, and plugins", None),
    66: ("Large tool-call argument payloads", "Tools, MCP, skills, and plugins", None),
    68: ("Large invoked skill bodies", "Tools, MCP, skills, and plugins", None),
    69: ("Unnecessary skill supporting-document reads", "Tools, MCP, skills, and plugins", None),
    70: ("Verbose plugin or hook context injection", "Tools, MCP, skills, and plugins", None),
    71: ("Whole-file reads for small relevant sections", "Repository discovery and file reading", None),
    72: ("Repeated reads of unchanged files", "Repository discovery and file reading", None),
    73: ("Broad repository searches", "Repository discovery and file reading", None),
    76: ("Reading dependency or vendor source", "Repository discovery and file reading", None),
    77: ("Reading generated files", "Repository discovery and file reading", None),
    79: ("Searching without useful path or symbol boundaries", "Repository discovery and file reading", None),
    82: ("Repeated failure tracebacks", "Terminal, build, and test output", None),
    84: ("Repeated linter diagnostics", "Terminal, build, and test output", None),
    87: ("Repeated runtime log lines", "Terminal, build, and test output", None),
    91: ("Large Git diffs with irrelevant context", "Git, collaboration, and structured data", None),
    92: ("Generated-file or lockfile diffs", "Git, collaboration, and structured data", None),
    93: ("Verbose commit-history metadata", "Git, collaboration, and structured data", None),
    94: ("Repeated working-tree status dumps", "Git, collaboration, and structured data", None),
    95: ("Full pull-request discussions", "Git, collaboration, and structured data", None),
    96: ("Full issue-tracker histories", "Git, collaboration, and structured data", None),
    98: ("Large JSON responses with unused fields", "Git, collaboration, and structured data", None),
    99: ("Database results with unnecessary rows or columns", "Git, collaboration, and structured data", None),
    100: ("Repetitive metadata and serialization wrappers", "Git, collaboration, and structured data", None),
    101: ("Full web pages instead of relevant passages", "Web research and retrieval", None),
    102: ("Navigation, footer, and website boilerplate", "Web research and retrieval", LABEL),
    103: ("Excessive search-result counts", "Web research and retrieval", None),
    104: ("Duplicate sources containing the same information", "Web research and retrieval", None),
    105: ("Repeated fetching of unchanged pages", "Web research and retrieval", None),
    107: ("Overlapping retrieval chunks", "Web research and retrieval", None),
    108: ("Irrelevant retrieved passages", "Web research and retrieval", LABEL),
    109: ("Entire documents attached for narrow questions", "Web research and retrieval", None),
    110: ("Repeated retrieval after losing source references", "Web research and retrieval", None),
    111: ("Large image payloads", "Images, PDFs, and browser interaction", None),
    112: ("Repeated unchanged screenshots", "Images, PDFs, and browser interaction", None),
    113: ("Full-screen screenshots for small relevant regions", "Images, PDFs, and browser interaction", LABEL),
    114: ("Excessive screenshots during browser navigation", "Images, PDFs, and browser interaction", None),
    115: ("Multi-page PDF processing", "Images, PDFs, and browser interaction", None),
    116: ("PDF page-image processing alongside extracted text", "Images, PDFs, and browser interaction", None),
    117: ("Duplicate OCR and document-text inputs", "Images, PDFs, and browser interaction", None),
    119: ("Large image batches containing irrelevant images", "Images, PDFs, and browser interaction", LABEL),
    120: ("Browser retries repeatedly loading the same visual context", "Images, PDFs, and browser interaction", None),
    121: ("Full context copied to every agent", "Multi-agent workflows", None),
    122: ("Duplicate investigations across agents", "Multi-agent workflows", None),
    124: ("Verbose agent task briefs", "Multi-agent workflows", None),
    125: ("Repeated agent startup instructions", "Multi-agent workflows", None),
    126: ("Agent-to-agent coordination chatter", "Multi-agent workflows", None),
    127: ("Oversized agent result reports", "Multi-agent workflows", None),
    128: ("Parent agents rereading material already reviewed by workers", "Multi-agent workflows", None),
    129: ("Repeated review and revision rounds", "Multi-agent workflows", LABEL),
    130: ("Agents continuing after their work is complete", "Multi-agent workflows", LABEL),
    131: ("Ambiguous prompts causing clarification loops", "Retries, automation, and context rebuilding", None),
    132: ("Missing acceptance criteria causing rework", "Retries, automation, and context rebuilding", LABEL),
    134: ("Regeneration after partially completed responses", "Retries, automation, and context rebuilding", None),
    135: ("Invalid structured outputs requiring repair", "Retries, automation, and context rebuilding", None),
    136: ("Repeated unchanged-state polling", "Retries, automation, and context rebuilding", None),
    137: ("Model-powered hooks firing excessively", "Retries, automation, and context rebuilding", HIDDEN),
    138: ("Scheduled tasks repeating unchanged analysis", "Retries, automation, and context rebuilding", None),
    140: ("Background session-analysis model calls", "Retries, automation, and context rebuilding", HIDDEN),
}
SAME_AS = {121: 23, 122: 24, 127: 25}   # canvas row -> core leak id that already measures it
REVIEW = {1, 6, 17, 22, 37, 54, 69, 109, 115, 125, 131}   # spend to review, not all waste
# measured inside leak_report.py's core detectors: 25, 26, 27, 29, 30, 38 and 40 (#3), 72 and 76 (#7), 135 (#16)


def lid(n):
    """Finding key for canvas row n of the additional section."""
    return 1000 + n


def md5(text):
    return hashlib.md5(text.encode(errors="replace")).hexdigest()


def norm_lines(text):
    return [re.sub(r"\d+", "#", l.strip()) for l in text.splitlines() if l.strip()]


def json_leaf_chars(v):
    if isinstance(v, dict):
        return sum(json_leaf_chars(x) for x in v.values())
    if isinstance(v, list):
        return sum(json_leaf_chars(x) for x in v)
    return len(str(v))


def is_page_tool(name):
    return name == "WebFetch" or any(k in name for k in ("get_page_text", "read_page", "fetch", "scrape"))


def is_browser_tool(name):
    return any(k in name for k in ("claude-in-chrome", "playwright", "browser"))


def is_web_search(name):
    return name == "WebSearch" or any(k in name.lower() for k in ("web_search", "search_documentation"))

# ------------------------------------------------------------------ per-session detectors


def analyse(s, tasks, add, price, cache_cost=lambda tokens, usd: usd):
    calls, results = s.calls, sorted(s.results, key=lambda r: r["t"])
    if not calls:
        return
    first_ctx = s.start_ctx   # the real first call, even when the session began before the report window

    def out_cost(c, tokens):
        return tokens * price(c["model"])[1] / 1e6

    def tool_share(c):   # output cost of one tool call inside model call c
        return out_cost(c, c["out"]) / max(1, c["n_tools"]) if c else 0.0

    def texts(c):
        return [b.get("text", "") for b in c["blocks"] if b.get("type") == "text"]

    # A1 Long single-thread history replay: history beyond the limit, on every call
    over = [(c, c["ctx"] - first_ctx - HISTORY_LIMIT) for c in calls]
    over = [(c, x) for c, x in over if x > 0]
    if over:
        add(lid(1), sum(x * c["read_price"] for c, x in over),
            f"{len(over)} calls carried more than {HISTORY_LIMIT:,} tokens of history")

    # A5 Old tool results carried into later turns: replay after STALE_CALLS more calls
    stale, n = 0.0, 0
    for r in results:
        i = bisect.bisect_right(s.call_times, r["t"]) + STALE_CALLS - 1
        if i < len(s.call_times):
            cost = s.carry(s.call_times[i], r["tokens"] + r["image_tokens"])
            if cost:
                stale, n = stale + cost, n + 1
    if n:
        add(lid(5), stale, f"{n} tool results still carried {STALE_CALLS}+ calls later")

    # A6 Previous assistant answers repeatedly replayed
    replay = sum(s.carry(c["t"], s.tok(sum(map(len, texts(c))))) for c in calls)
    if replay:
        add(lid(6), replay, "assistant text re-read on later calls")

    # A8 Full transcripts copied between chats
    for p in s.prompts:
        if p["tokens"] >= TRANSCRIPT_MIN and len(TRANSCRIPT_MARK.findall(p["body"])) >= 4:
            add(lid(8), s.carry(p["t"], p["tokens"]), f"prompt of ~{p['tokens']:,} tokens looks like a pasted chat transcript")

    # A21 Missing prompt caching, A24 prefixes below the cacheable minimum,
    # A22 cold-cache requests, A35 cache writes never reused, A37 cache-write premium
    streams = [calls] + list(s.agents.values())
    uncached = below = cold = unused = premium = 0.0
    n_uncached = n_below = n_unused = 0
    started_before = [s.cut] + [a in s.agents_before for a in s.agents]   # first call here is not a cold start
    for stream, before in zip(streams, started_before):
        for i, c in enumerate(stream):
            pi, _, pr = price(c["model"])
            premium += cache_cost(c["cw"], c["cw"] * pi * (c["wmult"] - 1) / 1e6)
            if c["in"] > UNCACHED_MIN:
                uncached, n_uncached = uncached + cache_cost(c["in"], c["in"] * (pi - pr) / 1e6), n_uncached + 1
            elif c["cw"] == c["cr"] == 0 and c["in"] and c["ctx"] < min_cacheable(c["model"]):
                below, n_below = below + cache_cost(c["in"], c["in"] * (pi - pr) / 1e6), n_below + 1
            if i == 0 and not before:
                cold += c["cw"] * pi * c["wmult"] / 1e6
            if c["cw"] > 1_000:
                nxt = stream[i + 1] if i + 1 < len(stream) else None
                if not (nxt and nxt["t"] - c["t"] < s.ttl_s and nxt["cr"]):
                    unused, n_unused = unused + cache_cost(c["cw"], c["cw"] * pi * (c["wmult"] - 1) / 1e6), n_unused + 1
    if n_uncached:
        add(lid(21), uncached, f"{n_uncached} calls with {UNCACHED_MIN:,}+ uncached input tokens")
    if n_below:
        add(lid(24), below, f"{n_below} calls too short to cache")
    if cold:
        add(lid(22), cold, f"first cache write of the session and {len(s.agents)} helper agents")
    if n_unused:
        add(lid(35), unused, f"{n_unused} cache writes not read back within the cache lifetime")
    if premium:
        add(lid(37), premium, "cache-write price above the normal input price")

    # A34 Concurrent requests before cache creation completes: helper agents started together
    starts = sorted((a[0] for a in s.agents.values()), key=lambda c: c["t"])
    for prev, c in zip(starts, starts[1:]):
        if c["t"] - prev["t"] <= CONCURRENT_S and c["cw"] > 5_000 and prev["cw"] > 5_000:
            pi, _, pr = price(c["model"])
            add(lid(34), cache_cost(c["cw"], c["cw"] * (pi * c["wmult"] - pr) / 1e6), f"helper agent wrote ~{c['cw']:,} tokens of cache at the same moment as a sibling")

    # A45 Replanning after every minor update: plan/todo updates per task beyond the limit
    for tsk in tasks:
        plans = sorted((u for u in s.tool_uses.values()
                        if u["name"] in PLAN_TOOLS and tsk["start"] <= u["t"] < tsk["end"]), key=lambda u: u["t"])
        for k, u in enumerate(plans[PLAN_LIMIT:], PLAN_LIMIT + 1):
            add(lid(45), tool_share(u["call"]) + s.carry(u["t"], s.tok(len(json.dumps(u["input"])))),
                f"plan update {k} in one task")

    # A52 Repeating the user's question, A53 repeated explanations, A54 progress narration,
    # A58 reprinting artifacts, A60 truncated answers
    prompt_times = [p["t"] for p in s.prompts]
    answered, paragraphs, artifacts = set(), set(), set()
    for u in sorted(s.tool_uses.values(), key=lambda u: u["t"]):
        if u["name"] in EDIT_TOOLS:
            for k in ("content", "new_string"):
                for block in re.findall(r"```.*?\n(.*?)```", str(u["input"].get(k, "")), re.S) + [str(u["input"].get(k, ""))]:
                    if len(block) >= CODE_MIN:
                        artifacts.add(md5(block.strip()))
    narration, n_narration = 0.0, 0
    for c in calls:
        body = "\n".join(texts(c))
        k = bisect.bisect_right(prompt_times, c["t"]) - 1
        if body and k >= 0 and k not in answered:
            answered.add(k)
            first = re.split(r"(?<=[.!?])\s|\n", body.strip(), maxsplit=1)[0]
            a = set(re.findall(r"[a-z0-9_]{3,}", first.lower()))
            q = set(re.findall(r"[a-z0-9_]{3,}", s.prompts[k]["text"].lower()))
            if len(a) >= 8 and q and len(a & q) / len(a | q) >= ECHO_SIM:
                add(lid(52), out_cost(c, s.tok(len(first))) + s.carry(c["t"], s.tok(len(first))), "reply opened by restating the request")
        for para in re.split(r"\n\s*\n", body):
            if len(para) >= 300:
                h = md5(" ".join(para.lower().split()))
                if h in paragraphs:
                    add(lid(53), out_cost(c, s.tok(len(para))) + s.carry(c["t"], s.tok(len(para))), f"repeated a ~{s.tok(len(para)):,}-token explanation")
                paragraphs.add(h)
        for block in re.findall(r"```.*?\n(.*?)```", body, re.S):
            if len(block) >= CODE_MIN:
                h = md5(block.strip())
                if h in artifacts:
                    add(lid(58), out_cost(c, s.tok(len(block))) + s.carry(c["t"], s.tok(len(block))),
                        f"reprinted a ~{s.tok(len(block)):,}-token code block already written")
                artifacts.add(h)
        if c["n_tools"] and s.tok(len(body)) > NARRATION_KEEP:
            extra = s.tok(len(body)) - NARRATION_KEEP
            narration, n_narration = narration + out_cost(c, extra) + s.carry(c["t"], extra), n_narration + 1
        if c.get("stop") == "max_tokens":
            add(lid(60), out_cost(c, c["out"]), f"reply cut off at the output limit (~{c['out']:,} tokens)")
    if n_narration:
        add(lid(54), narration, f"{n_narration} tool-calling messages with more than {NARRATION_KEEP} tokens of text")

    # tool-result detectors
    discovery = 0
    seen = {"lint": set(), "trace": set(), "status": None, "image": {}, "line": {}}
    fetched, polls = {}, defaultdict(int)
    sources, doc_inputs = [], defaultdict(list)   # A104 web results so far; A116/A117 ways each document was read
    helper_reads = {}
    for r in s.helper_results:
        path = r["input"].get("file_path", "")
        if r["name"] == "Read" and path:
            helper_reads.setdefault(path, r["t"])
    prev = None
    radd = lambda leak, cost, detail: add(leak, cost, detail, ref=r["id"])   # per-result findings
    for r in results:
        name, inp, call = r["name"] or "", r["input"], r["call"]
        body, tokens = r["body"], r["tokens"]
        cmd = str(inp.get("command", "")) if name == "Bash" else ""
        path = inp.get("file_path", "") if name == "Read" else ""
        sliced = inp.get("offset") is not None or inp.get("limit") is not None
        lines = body.splitlines()

        if name in DISCOVERY_TOOLS:                                   # A65
            discovery += 1
            if discovery > DISCOVERY_LIMIT:
                radd(lid(65), tool_share(call) + s.carry(r["t"], tokens), f"{name} call {discovery} in one session")
        args = s.tok(len(json.dumps(inp)))
        if name not in EDIT_TOOLS | AGENT_TOOLS and args > ARGS_BIG:   # A66
            radd(lid(66), out_cost(call, args) + s.carry(r["t"], args) if call else 0.0, f"{name} called with ~{args:,} tokens of arguments")
        if path:
            if "/skills/" in path and not path.endswith("SKILL.md"):  # A69
                radd(lid(69), s.carry(r["t"], tokens), f"read skill document {path.rsplit('/', 1)[-1]}")
            if not sliced and tokens > WHOLE_FILE:                    # A71
                radd(lid(71), s.carry(r["t"], tokens - KEEP), f"whole-file read of {path.rsplit('/', 1)[-1]} (~{tokens:,} tokens)")
            if DEP_DIRS.search(path):                                 # A76
                radd(lid(76), s.carry(r["t"], tokens), f"read dependency file {path.rsplit('/', 1)[-1]}")
            elif GENERATED.search(path):                              # A77
                radd(lid(77), s.carry(r["t"], tokens), f"read generated file {path.rsplit('/', 1)[-1]}")
            if path.lower().endswith(".pdf"):                         # A115
                radd(lid(115), s.carry(r["t"], tokens + r["image_tokens"]), f"read PDF {path.rsplit('/', 1)[-1]}")
            if path in helper_reads and helper_reads[path] < r["t"]:  # A128
                radd(lid(128), s.carry(r["t"], tokens), f"re-read {path.rsplit('/', 1)[-1]} after a helper agent read it")
        if name in ("Grep", "Glob") or SEARCH_CMD.search(cmd):
            if len(lines) > SEARCH_LINES:                             # A73
                radd(lid(73), s.carry(r["t"], int(tokens * (1 - SEARCH_LINES / len(lines)))),
                    f"{name} returned {len(lines)} lines")
            bounded = inp.get("path") or inp.get("glob") or inp.get("type") or name == "Bash"
            if name == "Glob":
                bounded = inp.get("path") or not str(inp.get("pattern", "")).startswith("**")
            if not bounded and tokens > 1_000:                        # A79
                radd(lid(79), s.carry(r["t"], tokens - 1_000), f"{name} with no path or file-type limit (~{tokens:,} tokens)")
        if r["error"] and TRACEBACK.search(body):                     # A82
            key = md5("\n".join(norm_lines(body)[-5:]))
            if key in seen["trace"]:
                radd(lid(82), s.carry(r["t"], tokens), f"same traceback again (~{tokens:,} tokens)")
            seen["trace"].add(key)
        if LINT_CMD.search(cmd):                                      # A84
            key = (cmd.strip(), r["hash"])
            if key in seen["lint"]:
                radd(lid(84), s.carry(r["t"], tokens), f"unchanged lint output ({cmd[:40]})")
            seen["lint"].add(key)
        if tokens >= 1_000 and (name != "Read" or path.endswith(".log")):  # A87
            nl = norm_lines(body)
            dup = 1 - len(set(nl)) / len(nl) if len(nl) >= 20 else 0
            if dup > DUP_LINE_SHARE:
                radd(lid(87), s.carry(r["t"], int(tokens * dup)), f"{name} output {dup:.0%} repeated lines")
        if DIFF_CMD.search(cmd):
            if tokens > BIG:                                          # A91
                radd(lid(91), s.carry(r["t"], tokens - KEEP), f"git diff ~{tokens:,} tokens")
            gen = sum(len(sec) for sec in re.split(r"(?=^diff --git )", body, flags=re.M)
                      if re.match(r"diff --git a/(\S+)", sec) and GENERATED.search(re.match(r"diff --git a/(\S+)", sec).group(1)))
            if s.tok(gen) > 500:                                        # A92
                radd(lid(92), s.carry(r["t"], s.tok(gen)), f"~{s.tok(gen):,} tokens of lockfile/generated diff")
        if LOG_CMD.search(cmd) and not LOG_SHORT.search(cmd):         # A93
            meta = sum(len(l) for l in lines if re.match(r"(commit [0-9a-f]{7,}|Author:|Date:|Merge:)", l))
            if s.tok(meta) > 300:
                radd(lid(93), s.carry(r["t"], s.tok(meta)), f"~{s.tok(meta):,} tokens of commit metadata")
        if STATUS_CMD.search(cmd):                                    # A94
            if seen["status"] == r["hash"]:
                radd(lid(94), s.carry(r["t"], tokens), "unchanged git status")
            seen["status"] = r["hash"]
        if tokens > BIG:
            if PR_CMD.search(cmd) or "pull_request" in name:          # A95
                radd(lid(95), s.carry(r["t"], tokens - KEEP), f"PR discussion ~{tokens:,} tokens")
            if ISSUE_CMD.search(cmd) or any(k in name.lower() for k in ("issue", "jira", "linear", "asana", "clickup")):  # A96
                radd(lid(96), s.carry(r["t"], tokens - KEEP), f"issue history ~{tokens:,} tokens ({name})")
            if DB_CMD.search(cmd) or any(k in name.lower() for k in ("query", "sql")):  # A99
                radd(lid(99), s.carry(r["t"], tokens - KEEP), f"query result ~{tokens:,} tokens ({name})")
            if name != "Read" and body.lstrip()[:1] in "{[" and body.strip():        # A98
                radd(lid(98), s.carry(r["t"], tokens - KEEP), f"JSON result ~{tokens:,} tokens ({name})")
            if is_page_tool(name):                                    # A101
                radd(lid(101), s.carry(r["t"], tokens - KEEP), f"full page ~{tokens:,} tokens ({name})")
        if tokens > 2_000 and name != "Read" and body.lstrip()[:1] in "{[":   # A100
            try:
                wrapper = len(body) - json_leaf_chars(json.loads(body))
            except ValueError:
                wrapper = 0
            if wrapper > 0.5 * len(body):
                radd(lid(100), s.carry(r["t"], s.tok(int(wrapper - 0.5 * len(body)))), f"JSON keys and wrappers {wrapper / len(body):.0%} of {name} result")
        if is_web_search(name):                                       # A103
            urls = len(set(URL_RE.findall(body)))
            if urls > SEARCH_RESULTS:
                radd(lid(103), s.carry(r["t"], int(tokens * (1 - SEARCH_RESULTS / urls))), f"{urls} search results")
        if (is_page_tool(name) or is_web_search(name)) and tokens >= 500:   # A104
            words = body.lower().split()
            shingles = {hash(tuple(words[i:i + SHINGLE])) for i in range(len(words) - SHINGLE + 1)}
            where = inp.get("url") or inp.get("query")
            share = max((len(shingles & sh) / len(shingles) for w, sh in sources if w != where), default=0) if shingles else 0
            if share >= DUP_SOURCE:
                radd(lid(104), s.carry(r["t"], int(tokens * share)), f"{name} result {share:.0%} the same as an earlier source")
            sources.append((where, shingles))
        if path.lower().endswith(".pdf") or (name == "Read" and r["images"]):   # A116, A117
            doc_inputs[os.path.basename(path)].append(("pages", r))
        elif PDF_TEXT_CMD.search(cmd) or OCR_CMD.search(cmd):
            for doc in set(DOC_NAME.findall(cmd)):
                doc_inputs[doc].append(("ocr" if OCR_CMD.search(cmd) else "text", r))
        url = inp.get("url") if (is_page_tool(name) or "navigate" in name) else None
        if url:                                                       # A105, A110
            if url in fetched:
                lost = any(fetched[url] < x < r["t"] for x in s.comp_sorted)
                radd(lid(110) if lost else lid(105), tool_share(call) + s.carry(r["t"], tokens),
                    f"fetched {url[:60]} again" + (" after a compaction" if lost else ""))
            fetched[url] = r["t"]
        if name not in ("Read", "Bash") and any(k in name.lower() for k in ("search", "retriev", "docs")):  # A107
            dup = 0
            for l in lines:
                if len(l) >= 80:
                    h = md5(l.strip())
                    if seen["line"].get(h, r["id"]) != r["id"]:
                        dup += len(l)
                    seen["line"].setdefault(h, r["id"])
            if s.tok(dup) > 200:
                radd(lid(107), s.carry(r["t"], s.tok(dup)), f"~{s.tok(dup):,} tokens of passages already retrieved")
        for h, itok in r["images"]:                                   # A111, A112, A120
            if itok > IMAGE_BIG:
                radd(lid(111), (itok - IMAGE_KEEP) * price(call["model"])[0] / 1e6 if call else 0.0, f"image ~{itok:,} tokens")
            if h in seen["image"]:
                retry = any(x["error"] and seen["image"][h] < x["t"] < r["t"] and is_browser_tool(x["name"] or "")
                            for x in results)
                radd(lid(120) if retry else lid(112), s.carry(r["t"], itok),
                    "same screenshot again" + (" after a failed browser action" if retry else ""))
            seen["image"][h] = r["t"]
        if r["images"] and prev is not None and prev["images"]:      # A114
            radd(lid(114), s.carry(r["t"], r["image_tokens"]), "screenshot taken right after another screenshot")
        counted_elsewhere = {"Read"} | EDIT_TOOLS | AGENT_TOOLS | PLAN_TOOLS | DISCOVERY_TOOLS   # 7, A45, A65
        if (not r["error"] and call and name not in counted_elsewhere and not r["images"]
                and not LINT_CMD.search(cmd) and not STATUS_CMD.search(cmd)):   # A136
            key = (name, md5(json.dumps(inp, sort_keys=True)), r["hash"])
            polls[key] += 1
            if polls[key] >= POLL_MIN:
                radd(lid(136), tool_share(call) + s.carry(r["t"], tokens), f"{name} returned the same result {polls[key]} times")
        prev = r

    for doc, reads in doc_inputs.items():   # the same document read both as page images and as text
        kinds = {k for k, _ in reads}
        if "pages" in kinds and len(kinds) > 1:
            kind, r = max(reads, key=lambda x: x[1]["t"])
            leak = lid(117) if "ocr" in kinds else lid(116)
            add(leak, s.carry(r["t"], r["tokens"] + r["image_tokens"]), f"{doc} read as page images and as extracted text", ref=r["id"])

    # A124 Verbose agent task briefs, A125 repeated agent startup, A126 coordination chatter,
    # A131 clarification loops
    for u in s.tool_uses.values():
        if u["name"] in AGENT_TOOLS:
            brief = s.tok(len(str(u["input"].get("prompt", ""))))
            if brief > BRIEF_BIG:
                add(lid(124), out_cost(u["call"], brief - BRIEF_BIG), f"agent brief ~{brief:,} tokens")
        elif u["name"] == "SendMessage":
            size = s.tok(len(json.dumps(u["input"])))
            add(lid(126), out_cost(u["call"], size) + s.carry(u["t"], size), "message sent to another agent")
        elif u["name"] == "AskUserQuestion":
            add(lid(131), u["call"]["cost"], "clarifying question asked")
    fresh = [calls for agent, calls in sorted(s.agents.items(), key=lambda kv: kv[1][0]["t"]) if agent not in s.agents_before]
    for a in (fresh if s.agents_before else fresh[1:]):
        c = a[0]
        pi, _, pr = price(c["model"])
        add(lid(125), (c["in"] * pi + c["cw"] * pi * c["wmult"] + c["cr"] * pr) / 1e6, f"helper agent startup ~{c['ctx']:,} tokens")
    for p in s.prompts:
        if p["text"].lstrip().startswith(COORDINATION):
            add(lid(126), s.carry(p["t"], p["tokens"]), "message from another agent")
        if p["docs"] or p["tokens"] > 10_000:                         # A109
            add(lid(109), s.carry(p["t"], p["tokens"]), f"prompt with an attached document (~{p['tokens']:,} tokens of text)")

    # A134 Regeneration after partially completed responses: turns the user interrupted
    for ti in s.interrupts:
        k = bisect.bisect_right(prompt_times, ti) - 1
        start = prompt_times[k] if k >= 0 else 0
        cost = sum(c["cost"] for c in calls if start <= c["t"] < ti)
        if cost:
            add(lid(134), cost, "turn interrupted before it finished")

    injected(s, add)
    # inputs for A138: the exact first request and the tool results it produced
    first = next((p["text"] for p in s.prompts if not p["text"].lstrip().startswith("<")), "")
    s.first_request = md5(" ".join(first.lower().split())) if len(first.strip()) >= 20 else None
    s.result_hashes = {r["hash"] for r in results if not r["error"] and r["tokens"] >= 50}


def injected(s, add):
    """Detectors on what Claude Code injects and records as attachments: instruction files,
    MCP-server and hook context, prompt snapshots and invoked skill bodies.
    A14 overlapping directory instructions, A16 duplicate rules across layers, A17 always-loaded
    guidance, A18 stale memory entries, A19 few-shot examples, A68 skill bodies, A70 injected context."""
    snaps = [(t, a) for t, a, _ in s.attachments if a.get("type") == "prompt_snapshot"]

    def examples(text):
        return sum(map(len, EXAMPLE_RE.findall(text)[EXAMPLE_KEEP:]))

    for t, a, rendered in s.attachments:
        kind = a.get("type")
        if kind == "instructions":
            seen, guidance = {}, 0
            for f in a.get("files") or []:
                path, layer, content = f.get("path", ""), f.get("type", ""), f.get("content", "")
                name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
                dup = {14: 0, 16: 0}
                for line in content.splitlines():
                    key = " ".join(line.split()).lower()
                    if len(key) < DUP_LINE_MIN or key.startswith("```"):
                        continue
                    other = seen.get(key)
                    if other and other[0] != path:   # A14 two directory levels, A16 two layers
                        dup[14 if layer == other[1] == "Project" else 16] += len(line)
                    seen.setdefault(key, (path, layer))
                for leak, chars in dup.items():
                    if s.tok(chars) > 50:
                        add(lid(leak), s.carry(t, s.tok(chars)), f"{name} repeats ~{s.tok(chars):,} tokens of an earlier instruction file")
                if layer in ("Project", "Local"):
                    guidance += s.tok(len(content))
                if layer == "AutoMem":                                    # A18 index lines whose memory file is gone
                    stale = [l for l in content.splitlines() for m in MEMORY_LINK.findall(l)
                             if not os.path.isabs(m) and not os.path.exists(os.path.join(os.path.dirname(path), m))]
                    if stale:
                        add(lid(18), s.carry(t, s.tok(sum(map(len, stale)))),
                            f"memory index lines pointing to deleted memory files: {len(stale)}")
                if examples(content):                                     # A19
                    add(lid(19), s.carry(t, s.tok(examples(content))), f"{name}: more than {EXAMPLE_KEEP} examples")
            if guidance > GUIDANCE_KEEP:                                  # A17
                add(lid(17), s.carry(t, guidance - GUIDANCE_KEEP),
                    f"~{guidance:,} tokens of always-loaded project guidance (review what every session needs)")
        elif kind == "mcp_instructions_delta":                            # A70
            for name, block in zip(a.get("addedNames") or [], a.get("addedBlocks") or []):
                if s.tok(len(block)) > INJECT_KEEP:
                    add(lid(70), s.carry(t, s.tok(len(block)) - INJECT_KEEP), f"{name} server instructions ~{s.tok(len(block)):,} tokens")
        elif str(kind).startswith("hook_"):
            size = s.tok(rendered or len(json.dumps(a)))
            if size > INJECT_KEEP:
                add(lid(70), s.carry(t, size - INJECT_KEEP), f"{kind} injected ~{size:,} tokens")

    # A19 in the system prompt and tool descriptions, which stay loaded until the next snapshot
    for k, (t, a) in enumerate(snaps):
        end = next((x for x, b in snaps[k + 1:] if b.get("tools") or b.get("systemPrompt")), float("inf"))
        chars = examples(json.dumps(a.get("systemPrompt") or ""))
        chars += sum(examples(str(x.get("description", ""))) for x in a.get("tools") or [])
        if chars:
            add(lid(19), s.tok(chars) * s.read_span(t, end), f"~{s.tok(chars):,} tokens of examples beyond {EXAMPLE_KEEP} per tool or prompt")

    for b in s.skill_bodies:                                              # A68
        use = s.tool_uses.get(b["id"])
        if b["tokens"] > SKILL_BIG and (use is None or use["name"] == "Skill"):
            name = str(use["input"].get("skill", "")) if use else "a skill"
            add(lid(68), s.carry(b["t"], b["tokens"] - SKILL_KEEP), f"invoked {name}: ~{b['tokens']:,}-token skill body")


def min_cacheable(model):
    """Minimum cacheable prompt length; verify against the prompt-caching docs for new models."""
    return 1_024 if "sonnet" in (model or "").lower() else 4_096

# ------------------------------------------------------------------ cross-session detectors


def cross_session(sessions, add_finding):
    """A7 repeated pastes, A9 conversation forks, A10 frequent fresh starts, A138 unchanged reruns."""
    by_project = defaultdict(list)
    for s in sessions:
        by_project[s.project].append(s)
    owner = {}
    for ss in by_project.values():
        ss.sort(key=lambda s: s.calls[0]["t"])
        pasted, prev, requests = set(), None, defaultdict(list)
        for s in ss:
            if s.first_request and not s.cut:   # A138 the same request again, finding the same tool results
                for e in requests[s.first_request]:
                    same = len(s.result_hashes & e.result_hashes) / len(s.result_hashes) if len(s.result_hashes) >= 3 else 0
                    if same >= UNCHANGED_SHARE:
                        add_finding(lid(138), s, s.cost + s.helper_cost,
                                    f"same request as session {e.sid[:8]}, {same:.0%} of tool results unchanged")
                        break
                requests[s.first_request].append(s)
            for p in s.prompts:
                for para in re.split(r"\n\s*\n", p["body"]):
                    if len(para) >= PASTE_MIN:
                        h = md5(" ".join(para.split()))
                        if h in pasted:
                            add_finding(lid(7), s, s.carry(p["t"], s.tok(len(para))), f"pasted the same ~{s.tok(len(para)):,}-token text again")
                        pasted.add(h)
            shared = {owner[u] for u in s.uuids if u in owner}
            if shared and not s.cut:
                inherited = max(0, s.calls[0]["ctx"] - START_BASELINE)
                add_finding(lid(9), s, inherited * s.prefix_read[-1],
                            f"forked from session {min(shared)[:8]}, inheriting ~{inherited:,} tokens")
            for u in s.uuids:
                owner.setdefault(u, s.sid)
            if prev and not s.cut and s.calls[0]["t"] - prev.calls[-1]["t"] < RESTART_GAP and s.first_edit < float("inf"):
                cost = sum(c["cost"] for c in s.calls if c["t"] < s.first_edit)
                add_finding(lid(10), s, cost, f"restarted {(s.calls[0]['t'] - prev.calls[-1]['t']) / 60:.0f} min after the last session; rebuilt context before the first edit")
            prev = s
