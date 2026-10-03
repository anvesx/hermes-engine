#!/usr/bin/env python3
"""
leak_report.py - rank token-leak categories by estimated cost, from Claude Code transcripts.

By default the report shows 50 curated categories (leak_categories.py), each summing one or more
detectors. --all prints the full canvas list instead: the 11 core leaks (1-11), 11 additional
leaks (12-22), three breakdowns of #4 Many agents (4a-4c), and the canvas's other 109 categories
(A rows, detected in leak_extra.py) in a second table; --all --core hides that second table.

Works on existing history: Claude Code already saves every session as JSONL under
~/.claude/projects/, so most leaks need no setup. The hook events from metrics_hook.py
(optional) add idle-usage detection and frustration ratings.

  python3 leak_report.py                       # all sessions
  python3 leak_report.py --since 2026-09-01 --md leak_report.md
  python3 leak_report.py --ttl 5m              # API-key users (5-minute cache)

How "cost" is estimated
  Token counts per model call come from the transcript (exact). The size of individual items
  (a tool result, a prompt) is estimated at 4 characters per token; images from their pixel size.
  A leaked item is charged for every later call that re-reads it, at the cache-read price, until
  the next compaction. All prices are API list prices: for subscription users this is
  API-equivalent usage, which is what drains the plan's allowance.
"""
import argparse
import base64
import bisect
import glob
import hashlib
import json
import os
import re
import statistics
import struct
from collections import Counter, defaultdict
from datetime import datetime, timezone

import leak_categories
import leak_extra
from leak_extra import lid

# ------------------------------------------------------------------ settings

# in, out, cache read per MTok, by model version (Anthropic first-party list prices). Versions of one family
# are priced differently (Opus 4.8 is $5/$25, Opus 5.5 $4/$20), so match the version, longest id first.
PRICES = {
    "claude-fable-5-1": (10.00, 50.00, 0.25), "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20), "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50), "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50), "claude-opus-4-5": (5.00, 25.00, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20), "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30), "claude-sonnet-4-5": (3.00, 15.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
PRICE_IDS = sorted(PRICES, key=len, reverse=True)
# a version not listed above is priced as the family's current model
FAMILY_PRICES = {"fable": PRICES["claude-fable-5-1"], "opus": PRICES["claude-opus-5-5"],
                 "sonnet": PRICES["claude-sonnet-5-5"], "haiku": PRICES["claude-haiku-4-5"]}
CHEAPER = PRICES["claude-sonnet-5-5"]   # what a simple task would have cost on the current Sonnet
WRITE_MULT = {"ephemeral_5m_input_tokens": 1.25, "ephemeral_1h_input_tokens": 2.0}   # cache-write price / input price
SYNTHETIC = "<synthetic>"   # messages Claude Code writes itself (errors, placeholders): not model calls
TOP_TIER = ("opus", "fable")
# Characters per token for item-size estimates (tool results, prompts, injected text). Per-call totals come
# from usage and need no estimate. Each session measures its own ratio per model (Session._calibrate); these
# defaults apply when it has too few samples: pooled medians of that same measurement over 166 tool results
# (new: 2.37, n=121; old: 3.10, n=45). The tokenizer introduced with Opus 4.7 (also Opus 5.x, Fable,
# Sonnet 5.x) gives ~30% more tokens for the same text than the one before it.
CHARS_PER_TOKEN = {"new": 2.37, "old": 3.10}
OLD_TOKENIZER = ("claude-opus-4-6", "claude-opus-4-5", "claude-opus-4-1", "claude-opus-4-2", "claude-sonnet-4",
                 "claude-sonnet-3", "claude-haiku", "claude-3")   # anything else (incl. unknown models) is "new"
CALIBRATE_MIN = 10             # clean samples a model needs in a session to use the session's own ratio
CALIBRATE_CHARS = 8_000        # tool results this large make the context-growth measurement precise
CALIBRATE_RANGE = (1.2, 6.0)   # ratios outside this are measurement noise, not text
START_BASELINE = 10_000        # starting context considered reasonable
CARRY_MIN = 20_000             # history carried into a new task before it counts as a leak
TASK_GAP_S = 30 * 60           # an untagged prompt after this much idle time starts a new task
EXPLORE_LIMIT = 15             # reads/searches before the first edit considered reasonable
BIG_RESULT = 4_000             # tool result size that counts as oversized
BIG_KEEP = 2_000               # portion of an oversized result that is charged as useful
IMAGE_DEFAULT = 1_600          # tokens for an image whose size can't be read
TRIVIAL_TEXT = 300             # a reply this short, with no tool calls, is a trivial turn
THINK_BASELINE = 1_000         # reasoning tokens considered reasonable on a trivial turn
THINK_LIMIT = 3_000            # reasoning tokens on a trivial turn before it counts as a leak
VISUAL_LIMIT = 3               # edit -> screenshot cycles per task considered reasonable
FORK_MIN = 50_000              # a helper agent starting this large inherited its parent's context
REPORT_BIG = 2_500             # helper-agent report size that counts as oversized
REPORT_KEEP = 1_000            # portion of an agent report that is charged as useful
RELEARN_MIN = 2                # earlier sessions that explored a file before re-reading counts
REPEAT_SIM = 0.6               # first-prompt word overlap that counts as the same task
SIMPLE_CATEGORIES = {"docs", "explain", "question", "rename", "chore", "commit"}
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
DEP_DIRS = re.compile(r"(^|/)(node_modules|\.venv|venv|dist|build|target|\.next|vendor|__pycache__)/")
ERROR_TEXT = re.compile(r"(error|failed|traceback|exception|exit code [1-9]|not found)", re.I)
DENIED_RE = re.compile(r"(doesn't want to proceed|permission|denied|rejected|not allowed|blocked)", re.I)
SCHEMA_RE = re.compile(r"(InputValidationError|invalid (input|param|argument|type)|required (parameter|property)|"
                       r"missing required|schema|unexpected (field|parameter|property))", re.I)
WRONG_ID_RE = re.compile(r"(not found|no such|does not exist|unknown (id|tool)|\b404\b)", re.I)
TAG_RE = re.compile(r"^\s*\[([A-Za-z][\w-]*)\]")
# same pattern as metrics_hook.py, so both scripts agree on what a correction is
CORRECTION_RE = re.compile(
    r"^\s*(no\b|nope\b|wrong\b|that'?s not|that is not|not what i|undo\b|revert\b|stop\b|"
    r"don'?t\b|you (broke|missed|forgot|ignored)|i said\b|again\b)", re.I)

# id: (label, name, category). Labels and categories follow the "Leak Categories" canvas.
LEAKS = {
    1: ("1", "Heavy starting context", "Persistent instructions and memory"),
    2: ("2", "Sessions that never end", "Conversation history"),
    3: ("3", "Losing the cache", "Cache misses and invalidation"),
    4: ("4", "Many agents", "Multi-agent workflows"),
    23: ("4a", "Fork context duplication", "Multi-agent workflows"),
    24: ("4b", "Overlapping agents", "Multi-agent workflows"),
    25: ("4c", "Verbose agent reports", "Multi-agent workflows"),
    5: ("5", "No clear direction", "Repository discovery and file reading"),
    6: ("6", "Bigger model than needed", "Model selection and reasoning"),
    7: ("7", "Too much tool output", "Tools, MCP, skills, and plugins"),
    8: ("8", "Wordy responses", "Answer and artifact generation"),
    9: ("9", "Retry loops", "Retries, automation, and context rebuilding"),
    10: ("10", "Usage while idle", "Retries, automation, and context rebuilding"),
    11: ("11", "No visibility", "Observability coverage"),
    12: ("12", "MCP tool schema bloat", "Tools, MCP, skills, and plugins"),
    13: ("13", "Unused skills/plugins", "Tools, MCP, skills, and plugins"),
    14: ("14", "Screenshot accumulation", "Images, PDFs, and browser interaction"),
    15: ("15", "Repeated tasks across sessions", "Conversation history"),
    16: ("16", "Failed/denied tool calls", "Retries, automation, and context rebuilding"),
    17: ("17", "Noisy commands", "Terminal, build, and test output"),
    18: ("18", "High effort on trivial turns", "Model selection and reasoning"),
    19: ("19", "Compaction cost", "Retries, automation, and context rebuilding"),
    20: ("20", "Correction churn", "Retries, automation, and context rebuilding"),
    21: ("21", "Visual iteration loops", "Images, PDFs, and browser interaction"),
    22: ("22", "Re-learning the codebase", "Repository discovery and file reading"),
    26: ("3a", "Cache expired after a break", "Cache misses and invalidation"),
}
PARENT = {23: 4, 24: 4, 25: 4, 26: 3}
SPEND_NOT_WASTE = {4, 15}   # reported as spend to review, not counted as pure waste
NOT_RECORDED = {   # older Claude Code versions don't record what was loaded, only what was used
    12: "needs the loaded tool definitions, which only newer Claude Code versions record (part of #1)",
    13: "needs the loaded skill listings, which only newer Claude Code versions record (part of #1)",
}
EFFORT_CMD = re.compile(r"<command-name>/effort</command-name>")


def tokenizer(model):
    m = (model or "").lower()
    return "old" if any(k in m for k in OLD_TOKENIZER) else "new"


UNITS = "usd"   # set_units("tokens") weighs every token as 1, so every cost below reads as a token count


def set_units(units):
    """'usd' prices calls at API list prices (the default); 'tokens' counts tokens instead."""
    global UNITS
    UNITS = units


def cache_cost(tokens, usd):
    """A cache miss sends no extra tokens: it turns cheap reads into dearer writes of the same tokens. So in token
    units the cache detectors report the tokens written (a cache event), and in dollars the price difference."""
    return tokens if UNITS == "tokens" else usd


def fmt_cost(x):
    return f"{x / 1e6:,.1f}M tokens" if UNITS == "tokens" else f"${x:,.2f}"


def price(model):
    if UNITS == "tokens":
        return (1e6, 1e6, 1e6)   # cost = tokens; carry() = tokens x calls that re-read them
    m = (model or "").lower()
    version = next((k for k in PRICE_IDS if k in m), None)
    if version:
        return PRICES[version]
    return next((p for k, p in FAMILY_PRICES.items() if k in m), FAMILY_PRICES["sonnet"])


def write_mult(usage, default):
    """Cache-write price as a multiple of the input price. Newer transcripts split writes by cache lifetime
    (5m: 1.25x, 1h: 2x); writes without that split use `default` (from --ttl)."""
    if UNITS == "tokens":
        return 1.0
    total = usage.get("cache_creation_input_tokens", 0) or 0
    split = usage.get("cache_creation") or {}
    if not total or not isinstance(split, dict):
        return default
    known = {k: split.get(k, 0) or 0 for k in WRITE_MULT}
    rest = max(0, total - sum(known.values()))
    return (sum(n * WRITE_MULT[k] for k, n in known.items()) + rest * default) / total


def top_tier(model):
    m = (model or "").lower()
    return any(k in m for k in TOP_TIER)


def ts_of(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(c.get("text", "")) if isinstance(c, dict) else len(str(c)) for c in content)
    return len(json.dumps(content)) if content else 0


def text_of(content, limit=4000):
    if isinstance(content, str):
        return content[:limit]
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))[:limit]
    return ""


def image_tokens(block):
    """Tokens for one base64 image block: (w * h) / 750 after the API's downscaling."""
    w = h = 0
    try:
        raw = base64.b64decode((block.get("source") or {}).get("data", "")[:65536])
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", raw[16:24])
        elif raw[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    break
                i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    except Exception:
        pass
    if not w or not h:
        return IMAGE_DEFAULT
    scale = min(1.0, 1568 / max(w, h), (1_150_000 / (w * h)) ** 0.5)
    return int(w * scale * h * scale / 750)


def prompt_words(text):
    return set(re.findall(r"[a-z0-9_]{3,}", TAG_RE.sub("", text, count=1).lower()))

# ------------------------------------------------------------------ loading


def load_sessions(root, since):
    """Group transcript entries by session; mark helper-agent entries and which agent wrote them."""
    sessions = defaultdict(list)
    for path in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
        helper_file = "subagent" in path.lower() or os.path.basename(path).startswith("agent-")
        project = os.path.relpath(path, root).split(os.sep)[0]
        try:
            with open(path, errors="replace") as f:
                for n, line in enumerate(f):
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    t = ts_of(e.get("timestamp", "")) if e.get("timestamp") else None
                    if t is None or t < since:
                        continue
                    sid = e.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
                    e["_t"], e["_n"], e["_project"] = t, n, project
                    e["_helper"] = bool(e.get("isSidechain")) or helper_file
                    e["_agent"] = (path if helper_file else e.get("agentId") or "sidechain") if e["_helper"] else None
                    sessions[sid].append(e)
        except OSError:
            continue
    for evs in sessions.values():
        evs.sort(key=lambda e: (e["_t"], e["_n"]))
    return sessions


def load_hook_prompts(path):
    prompts = defaultdict(list)
    ratings = defaultdict(list)
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event") == "UserPromptSubmit":
                    (ratings if e.get("kind") == "rating" else prompts)[e.get("session_id")].append(e)
    return prompts, ratings

# ------------------------------------------------------------------ per-session analysis


class Session:
    def __init__(self, sid, entries, write_mult, ttl_s, hook_prompts):
        self.sid, self.project = sid, entries[0]["_project"]
        self.write_mult, self.ttl_s = write_mult, ttl_s
        self.hook_prompts = hook_prompts
        self.calls, self.helper_calls = [], []      # assistant model calls
        self.agents = defaultdict(list)             # helper calls by agent
        self.prompts, self.tool_uses, self.results = [], {}, []
        self.helper_tool_uses, self.helper_results = {}, []
        self.compactions, self.summaries = [], []
        self.interrupts, self.uuids = [], set()
        self.attachments, self.skill_bodies = [], []   # what Claude Code injected: (t, attachment, rendered chars)
        self._parse(entries)
        self._segments()
        self._calibrate()
        self._size_items()

    # -- item sizes ----------------------------------------------------------------
    def _calibrate(self):
        """Characters per token by model, measured from this session. A sample is a text tool result of
        CALIBRATE_CHARS+ characters, the only result between two calls of one stream (main session or one
        agent) on the same model, with no prompt, injected attachment or compaction in between. The second
        call's context grew by exactly the first call's output plus that result, so
        result tokens = ctx(next) - ctx(call) - out(call). A model with fewer than CALIBRATE_MIN samples
        uses its tokenizer's default."""
        samples = defaultdict(list)
        injected = sorted(t for t, _, _ in self.attachments)
        streams = [(self.calls, self.results, self.prompts)]
        streams += [(calls, self.helper_results, []) for calls in self.agents.values()]
        for calls, results, prompts in streams:
            by_id = {r["id"]: r for r in results}
            for a, b in zip(calls, calls[1:]):
                uses = [x for x in a["blocks"] if x.get("type") == "tool_use"]
                r = by_id.get(uses[0].get("id")) if len(uses) == 1 else None
                if (not r or r["images"] or r["chars"] < CALIBRATE_CHARS or a["model"] != b["model"]
                        or any(a["t"] < x <= b["t"] for x in self.comp_sorted)
                        or any(a["t"] < p["t"] <= b["t"] for p in prompts)
                        or (calls is self.calls and any(a["t"] < x <= b["t"] for x in injected))):
                    continue
                grew = b["ctx"] - a["ctx"] - a["out"]
                if grew > 0 and CALIBRATE_RANGE[0] <= r["chars"] / grew <= CALIBRATE_RANGE[1]:
                    samples[a["model"]].append(r["chars"] / grew)
        self.calibration_samples = dict(samples)
        self.calibration = {m: (statistics.median(v), len(v)) for m, v in samples.items() if len(v) >= CALIBRATE_MIN}
        models = Counter(c["model"] for c in self.calls or self.helper_calls)
        self.main_model = models.most_common(1)[0][0] if models else ""

    def chars_per_token(self, model=None):
        model = model or self.main_model
        return self.calibration[model][0] if model in self.calibration else CHARS_PER_TOKEN[tokenizer(model)]

    def tok(self, chars, model=None):
        """Estimated tokens for `chars` characters of text read or written by `model` (default: the main model)."""
        return int(chars / self.chars_per_token(model))

    def _size_items(self):
        for r in self.results + self.helper_results:
            r["tokens"] = self.tok(r["chars"], r["call"]["model"] if r["call"] else None)
        for x in self.prompts + self.skill_bodies:
            x["tokens"] = self.tok(x["chars"])
        self.summaries = [(t, self.tok(chars)) for t, chars in self.summaries]

    # -- parsing ---------------------------------------------------------------
    def _result(self, e, b):
        content = b.get("content")
        txt = text_of(content)
        body = text_of(content, 50_000)
        images = [(hashlib.md5(json.dumps(c.get("source", {}), sort_keys=True).encode()).hexdigest(), image_tokens(c))
                  for c in content if isinstance(c, dict) and c.get("type") == "image"] if isinstance(content, list) else []
        return {"t": e["_t"], "id": b.get("tool_use_id"), "agent": e["_agent"],
                "chars": text_len(content), "images": images, "image_tokens": sum(n for _, n in images),
                "is_error": bool(b.get("is_error")),
                "error": bool(b.get("is_error")) or bool(ERROR_TEXT.search(txt[:600])),
                "text": txt, "body": body, "hash": hashlib.md5(body.encode(errors="replace")).hexdigest()}

    def _parse(self, entries):
        by_id, boundaries = {}, []
        for e in entries:
            msg = e.get("message") or {}
            content = msg.get("content")
            if not e["_helper"] and e.get("uuid"):
                self.uuids.add(e["uuid"])
            if e.get("type") == "attachment":
                if not e["_helper"] and isinstance(e.get("attachment"), dict):
                    self.attachments.append((e["_t"], e["attachment"], len(str(e.get("rendered") or ""))))
                continue
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                if not e["_helper"]:
                    boundaries.append(e["_t"])
                continue
            if e.get("isCompactSummary"):
                if not e["_helper"]:
                    self.summaries.append((e["_t"], text_len(content)))   # chars until _size_items
                continue
            if e.get("type") == "assistant" and msg.get("usage") and msg.get("model") != SYNTHETIC:
                mid = msg.get("id") or e.get("uuid")
                c = by_id.get(mid)
                if c is None:
                    c = {"t": e["_t"], "model": msg.get("model", ""), "blocks": [],
                         "helper": e["_helper"], "agent": e["_agent"]}
                    by_id[mid] = c
                    if e["_helper"]:
                        self.helper_calls.append(c)
                        self.agents[e["_agent"]].append(c)
                    else:
                        self.calls.append(c)
                c["usage"] = msg["usage"]
                c["stop"] = msg.get("stop_reason") or c.get("stop")
                if isinstance(content, list):
                    c["blocks"].extend(b for b in content if isinstance(b, dict))
            elif e.get("type") == "user":
                if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            (self.helper_results if e["_helper"] else self.results).append(self._result(e, b))
                elif e.get("isMeta") and e.get("sourceToolUseID"):   # an invoked skill's body
                    if not e["_helper"]:
                        self.skill_bodies.append({"t": e["_t"], "id": e["sourceToolUseID"], "chars": text_len(content)})
                elif not e["_helper"] and not e.get("isMeta"):
                    txt = text_of(content)
                    docs = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "document") if isinstance(content, list) else 0
                    if "interrupted by user" in txt:
                        self.interrupts.append(e["_t"])
                    elif txt or docs:
                        body = text_of(content, 50_000)
                        self.prompts.append({"t": e["_t"], "chars": len(body), "text": txt, "body": body, "docs": docs})
        # one compaction writes a boundary marker and a summary; count boundaries when present
        self.compactions = boundaries or [t for t, _ in self.summaries]

        for c in self.calls + self.helper_calls:
            u = c["usage"]
            c["in"] = u.get("input_tokens", 0) or 0
            c["cw"] = u.get("cache_creation_input_tokens", 0) or 0
            c["cr"] = u.get("cache_read_input_tokens", 0) or 0
            c["out"] = u.get("output_tokens", 0) or 0
            c["ctx"] = c["in"] + c["cw"] + c["cr"]
            c["wmult"] = write_mult(u, self.write_mult)
            pi, po, pr = price(c["model"])
            c["cost"] = (c["in"] * pi + c["cw"] * pi * c["wmult"] + c["cr"] * pr + c["out"] * po) / 1e6
            c["read_price"] = pr / 1e6
            uses = self.helper_tool_uses if c["helper"] else self.tool_uses
            c["n_tools"] = 0
            for b in c["blocks"]:
                if b.get("type") == "tool_use":
                    c["n_tools"] += 1
                    uses[b.get("id")] = {"t": c["t"], "name": b.get("name"), "input": b.get("input") or {}, "call": c}
        for results, uses in ((self.results, self.tool_uses), (self.helper_results, self.helper_tool_uses)):
            for r in results:
                tu = uses.get(r["id"])
                r["name"] = tu["name"] if tu else None
                r["input"] = tu["input"] if tu else {}
                r["call"] = tu["call"] if tu else None
        self.cost = sum(c["cost"] for c in self.calls)
        self.helper_cost = sum(c["cost"] for c in self.helper_calls)

    def _segments(self):
        """Calls between compactions; used to charge re-reads only until the next compaction."""
        self.call_times = [c["t"] for c in self.calls]
        self.prefix_read = [0.0]
        for c in self.calls:
            self.prefix_read.append(self.prefix_read[-1] + c["read_price"])
        self.comp_sorted = sorted(self.compactions)
        self.prefix_events = self._prefix_events()

    def _prefix_events(self):
        """Recorded changes to the cached prefix, as (time, cause, finding key), to explain cache rewrites."""
        out, tools, system, org = [], None, None, None
        for t, a, _ in self.attachments:
            kind = a.get("type")
            if kind == "prompt_snapshot":
                if a.get("tools"):
                    sig = [hashlib.md5(json.dumps(x, sort_keys=True).encode()).hexdigest() for x in a["tools"]]
                    if tools is not None and sig != tools:
                        out.append((t, "tool order changed", lid(29)) if sorted(sig) == sorted(tools)
                                   else (t, "tool definitions changed", lid(27)))
                    tools = sig
                if a.get("systemPrompt"):
                    text = json.dumps(a["systemPrompt"])
                    if system is not None and text != system:
                        out.append((t, "timestamp in the system prompt changed", lid(25))
                                   if re.sub(r"\d", "#", text) == re.sub(r"\d", "#", system)
                                   else (t, "system prompt changed", lid(26)))
                    system = text
            elif kind == "credential_org":
                if org is not None and a.get("organizationUuid") != org:
                    out.append((t, "switched organization (separate cache)", lid(40)))
                org = a.get("organizationUuid")
        out += [(p["t"], "effort changed", lid(38)) for p in self.prompts if EFFORT_CMD.search(p["text"])]
        return sorted(out, key=lambda x: x[0])

    def read_span(self, t0, t1):
        """Cache-read price summed over the main calls after t0 and before t1."""
        i = bisect.bisect_right(self.call_times, t0)
        j = bisect.bisect_left(self.call_times, t1)
        return self.prefix_read[j] - self.prefix_read[i] if j > i else 0.0

    def carry(self, t, tokens, until=None):
        """Cost of re-reading `tokens` on every main call after time t, until compaction or `until`."""
        if tokens <= 0:
            return 0.0
        i = bisect.bisect_right(self.call_times, t)
        k = bisect.bisect_right(self.comp_sorted, t)
        end_t = self.comp_sorted[k] if k < len(self.comp_sorted) else float("inf")
        if until is not None:
            end_t = min(end_t, until)
        j = bisect.bisect_left(self.call_times, end_t)
        return tokens * (self.prefix_read[j] - self.prefix_read[i]) if j > i else 0.0

    def next_call(self, t):
        i = bisect.bisect_right(self.call_times, t)
        return self.call_times[i] if i < len(self.call_times) else None

    def agent_carry(self, agent, t, tokens):
        """Cost of re-reading `tokens` on every later call of one helper agent."""
        return tokens * sum(c["read_price"] for c in self.agents.get(agent, []) if c["t"] > t)

    # -- tasks -------------------------------------------------------------------
    def tasks(self):
        out = []
        for n, p in enumerate(self.prompts):
            tag = TAG_RE.match(p["text"])
            i = bisect.bisect_left(self.call_times, p["t"])
            last_activity = self.call_times[i - 1] if i > 0 else (self.prompts[n - 1]["t"] if n else None)
            gap = last_activity is not None and p["t"] - last_activity >= TASK_GAP_S
            if not out or tag or gap:
                out.append({"start": p["t"], "category": tag.group(1).lower() if tag else None,
                            "prompt_tokens": p["tokens"], "by": "tag" if tag else ("gap" if gap else "start")})
        for n, tsk in enumerate(out):
            tsk["end"] = out[n + 1]["start"] if n + 1 < len(out) else float("inf")
            tsk["calls"] = [c for c in self.calls if tsk["start"] <= c["t"] < tsk["end"]]
        return out


# ------------------------------------------------------------------ leak detectors


def add_finding(findings, leak, s, cost, detail, ref=None, overlap=False):
    """ref: the tool result a finding is about, so a curated row merging two detectors counts it once.
    overlap: also recorded under another leak; kept for --all, skipped in the curated rows."""
    findings[leak].append({"cost": cost, "session": s.sid[:8], "project": s.project, "detail": detail,
                           "ref": ref and f"{s.sid}:{ref}", "overlap": overlap})


def analyse(s: Session, findings):
    if not s.calls:
        return
    tasks = s.tasks()
    first = s.calls[0]
    first_prompt = s.prompts[0]["tokens"] if s.prompts else 0
    prefix = max(0, first["ctx"] - first_prompt)
    results = sorted(s.results, key=lambda r: r["t"])

    def add(leak, cost, detail, ref=None, overlap=False):
        add_finding(findings, leak, s, cost, detail, ref, overlap)

    findings["_calibration"].append(s.calibration.get(s.main_model, (s.chars_per_token(), 0)))

    # 1. Heavy starting context: excess over the baseline, re-read on every call
    findings["_prefix_sizes"].append(prefix)
    if prefix > START_BASELINE:
        extra = prefix - START_BASELINE
        add(1, extra * s.prefix_read[-1], f"starting context ~{prefix:,} tokens over {len(s.calls)} calls")

    # 2. Sessions that never end: history carried from earlier tasks into later ones
    for tsk in tasks[1:]:
        if not tsk["calls"]:
            continue
        carried = tsk["calls"][0]["ctx"] - prefix - tsk["prompt_tokens"]
        if carried > CARRY_MIN:
            add(2, s.carry(tsk["start"], carried, until=tsk["end"]),
                f"new task ({tsk['category'] or 'after ' + str(TASK_GAP_S // 60) + ' min gap'}) carried ~{carried:,} old tokens")
    if len(s.compactions):
        findings["_compactions"].append(len(s.compactions))

    # 3. Losing the cache: large rewrites after the first call, with likely cause.
    # 3a. the ones caused by a break past the cache lifetime, so the curated row can show breaks alone.
    # 19. Compaction cost: rewrites right after a compaction, plus writing the summary.
    comp = s.comp_sorted
    compaction = {x: {"summary": 0, "rewrite": 0.0, "tokens": 0} for x in comp}
    for t, summary in s.summaries:
        k = bisect.bisect_right(comp, t + 5) - 1
        if k >= 0:
            compaction[comp[k]]["summary"] += summary
    for i in range(1, len(s.calls)):
        c, prev = s.calls[i], s.calls[i - 1]
        if c["cw"] > max(5_000, 0.5 * c["ctx"]):
            pi, _, pr = price(c["model"])
            premium = cache_cost(c["cw"], c["cw"] * (pi * c["wmult"] - pr) / 1e6)
            x = next((x for x in comp if prev["t"] < x <= c["t"]), None)
            if x is not None:
                compaction[x]["rewrite"] += premium
                compaction[x]["tokens"] += c["cw"]
                continue
            gap = c["t"] - prev["t"]
            if c["model"] != prev["model"]:
                cause = "model switch"
                add(lid(30), premium, f"~{c['cw']:,} tokens rewritten switching {prev['model']} -> {c['model']}")
            elif gap >= 3600:
                cause = f"break of {gap / 60:.0f} min"
                add(26, premium, f"~{c['cw']:,} tokens rewritten, {cause}")
            elif gap >= s.ttl_s:
                cause = f"break of {gap / 60:.0f} min (past cache lifetime)"
                add(26, premium, f"~{c['cw']:,} tokens rewritten, {cause}")
            else:
                event = next((x for x in s.prefix_events if prev["t"] < x[0] <= c["t"]), None)
                cause = event[1] if event else "context changed (tools, instructions, settings)"
                if event:
                    add(event[2], premium, f"~{c['cw']:,} tokens rewritten, {cause}")
            add(3, premium, f"~{c['cw']:,} tokens rewritten, {cause}")
    for x, cc in compaction.items():
        k = bisect.bisect_left(s.call_times, x) - 1
        out_price = price(s.calls[max(0, k)]["model"])[1]
        add(19, cc["summary"] * out_price / 1e6 + cc["rewrite"],
            f"compaction: ~{cc['summary']:,} summary tokens written, ~{cc['tokens']:,} tokens rewritten after")

    # 4. Many agents: helper spend (to review, not all waste)
    if s.helper_calls:
        add(4, s.helper_cost, f"{len(s.helper_calls)} helper calls, {s.helper_cost / max(1e-9, s.cost + s.helper_cost):.0%} of session cost")

    # 4a. Fork context duplication: helper agents that start with the parent's context
    for calls in s.agents.values():
        first_ctx = calls[0]["ctx"]
        if first_ctx > FORK_MIN:
            add(23, (first_ctx - START_BASELINE) * sum(c["read_price"] for c in calls),
                f"helper agent started with ~{first_ctx:,} tokens over {len(calls)} calls")

    # 4b. Overlapping agents: a file already read by a sibling agent, charged to the later reader
    readers = defaultdict(set)
    for r in sorted(s.helper_results, key=lambda r: r["t"]):
        path = r["input"].get("file_path", "")
        if r["name"] != "Read" or not path:
            continue
        if readers[path] and r["agent"] not in readers[path]:
            add(24, s.agent_carry(r["agent"], r["t"], r["tokens"]),
                f"{os.path.basename(path)} also read by a sibling agent (~{r['tokens']:,} tokens)")
        readers[path].add(r["agent"])

    # 5. No clear direction: exploration calls before the first edit, beyond the limit
    for tsk in tasks:
        uses = sorted([u for u in s.tool_uses.values() if tsk["start"] <= u["t"] < tsk["end"]], key=lambda u: u["t"])
        first_edit = next((u["t"] for u in uses if u["name"] in EDIT_TOOLS), None)
        if first_edit is None:
            continue
        explore = [u for u in uses if u["t"] < first_edit]
        if len(explore) > EXPLORE_LIMIT:
            calls = {id(u["call"]): u["call"] for u in explore[EXPLORE_LIMIT:]}
            add(5, sum(c["cost"] for c in calls.values()),
                f"{len(explore)} reads/searches before the first edit")

    # 6. Bigger model than needed: premium models on simple categories, and premium helpers
    for tsk in tasks if UNITS == "usd" else []:   # a model-choice question: in tokens a smaller model reads the same
        if tsk["category"] in SIMPLE_CATEGORIES:
            for c in tsk["calls"]:
                if top_tier(c["model"]):
                    pi, po, pr = CHEAPER
                    cheaper = (c["in"] * pi + c["cw"] * pi * c["wmult"] + c["cr"] * pr + c["out"] * po) / 1e6
                    add(6, c["cost"] - cheaper, f"[{tsk['category']}] task on {c['model']}")
    for c in s.helper_calls if UNITS == "usd" else []:
        if top_tier(c["model"]):
            pi, po, pr = CHEAPER
            cheaper = (c["in"] * pi + c["cw"] * pi * c["wmult"] + c["cr"] * pr + c["out"] * po) / 1e6
            add(6, c["cost"] - cheaper, f"helper agent on {c['model']}")
    findings["_main_cost"].append(s.cost)
    findings["_top_tier_cost"].append(sum(c["cost"] for c in s.calls if top_tier(c["model"])))

    # 7. Too much tool output: duplicate reads, dependency-folder hits, oversized results.
    # Split out by source: 14 images, 16 failed calls, 17 shell output, 4c agent reports.
    seen_reads, edited_since = {}, set()
    for r in results:
        name, inp = r["name"], r["input"]
        path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
        if name in EDIT_TOOLS and path:
            edited_since.add(path)
        if r["image_tokens"]:
            nxt = s.next_call(r["t"])
            add(14, s.carry(nxt, r["image_tokens"]) if nxt else 0.0,
                f"{name} image ~{r['image_tokens']:,} tokens kept in context")
        if r["is_error"] and "interrupted by user" not in r["text"]:
            kind = ("denied" if DENIED_RE.search(r["text"]) else "schema error" if SCHEMA_RE.search(r["text"])
                    else "wrong id/path" if WRONG_ID_RE.search(r["text"]) else "error")
            call = r["call"]
            wasted = call["out"] * price(call["model"])[1] / 1e6 / max(1, call["n_tools"]) if call else 0.0
            add(16, wasted + s.carry(r["t"], r["tokens"]), f"{name} {kind} (~{r['tokens']:,} tokens of error text)",
                ref=r["id"])
            if kind == "schema error":
                add(lid(135), wasted + s.carry(r["t"], r["tokens"]), f"{name} rejected its arguments")
        if name == "Read" and path:
            key = (path, inp.get("offset"), inp.get("limit"))
            if key in seen_reads and path not in edited_since:
                add(7, s.carry(r["t"], r["tokens"]), f"re-read {os.path.basename(path)} (~{r['tokens']:,} tokens)",
                    overlap=True)
                add(lid(72), s.carry(r["t"], r["tokens"]), f"re-read {os.path.basename(path)} (~{r['tokens']:,} tokens)")
                continue
            seen_reads[key] = r["t"]
            edited_since.discard(path)
        if name in AGENT_TOOLS:
            if r["tokens"] > REPORT_BIG:
                add(25, s.carry(r["t"], r["tokens"] - REPORT_KEEP),
                    f"agent report ~{r['tokens']:,} tokens ({str(inp.get('description', ''))[:40] or name})")
            continue
        dep_lines = [l for l in r["text"].splitlines() if DEP_DIRS.search(l)]
        if name in ("Grep", "Glob", "Bash", "LS") and len(dep_lines) >= 5:
            dep_tokens = int(r["tokens"] * len(dep_lines) / max(1, len(r["text"].splitlines())))
            add(7, s.carry(r["t"], dep_tokens), f"{name} returned results from dependency/build folders ({len(dep_lines)}+ lines)",
                overlap=True)
            add(lid(76), s.carry(r["t"], dep_tokens), f"{name} returned results from dependency/build folders ({len(dep_lines)}+ lines)")
        elif r["tokens"] > BIG_RESULT:
            what = os.path.basename(path) if path else (str(inp.get("command", ""))[:40] or name)
            add(17 if name == "Bash" else 7, s.carry(r["t"], r["tokens"] - BIG_KEEP),
                f"{name} result ~{r['tokens']:,} tokens ({what})", ref=r["id"])

    # 8. Wordy responses: output share and whole-file rewrites of existing files
    findings["_output_cost"].append(sum(c["out"] * price(c["model"])[1] / 1e6 for c in s.calls))
    read_paths = set()
    for u in sorted(s.tool_uses.values(), key=lambda u: u["t"]):
        path = u["input"].get("file_path", "")
        if u["name"] in ("Read", "Edit", "MultiEdit"):
            read_paths.add(path)
        elif u["name"] == "Write" and path in read_paths:
            out_tokens = s.tok(len(u["input"].get("content", "")), u["call"]["model"])
            add(8, out_tokens * price(u["call"]["model"])[1] / 1e6,
                f"rewrote whole file {os.path.basename(path)} (~{out_tokens:,} tokens)")

    # 9. Retry loops: the same failing tool call repeated; charge attempts after the second
    attempts = defaultdict(int)
    for r in results:
        if not r["call"]:
            continue
        key = (r["name"], hashlib.md5(json.dumps(r["input"], sort_keys=True).encode()).hexdigest())
        if r["error"]:
            attempts[key] += 1
            if attempts[key] >= 3:
                add(9, r["call"]["cost"], f"{r['name']} failed {attempts[key]} times with the same input",
                    ref=r["id"])
        else:
            attempts[key] = 0

    # 10. Usage while idle: prompts not typed by the developer (needs hook data). Only prompts after the
    # session's first hook record count: earlier ones were typed before the plugin was loaded.
    hp = s.hook_prompts.get(s.sid)
    if hp is not None:
        typed = [e["ts"] for e in hp]
        covered_from = min(typed) - 15
        for n, p in enumerate(s.prompts):
            if p["t"] >= covered_from and not any(abs(p["t"] - t) < 15 for t in typed):
                end = s.prompts[n + 1]["t"] if n + 1 < len(s.prompts) else float("inf")
                cost = sum(c["cost"] for c in s.calls if p["t"] <= c["t"] < end)
                if cost:
                    add(10, cost, "turn started without a typed prompt (scheduled task, loop or background message)")
        findings["_hook_sessions"].append(s.sid)

    # 12. MCP tool schema bloat: definitions of MCP tools the session never called, on every call
    used = {u["name"] for u in list(s.tool_uses.values()) + list(s.helper_tool_uses.values())}
    snaps = [(t, a["tools"]) for t, a, _ in s.attachments if a.get("type") == "prompt_snapshot" and a.get("tools")]
    if snaps:
        findings["_snapshot_sessions"].append(s.sid)
        findings["_mcp_tokens"].append(sum(s.tok(len(json.dumps(x))) for x in snaps[0][1]
                                           if str(x.get("name", "")).startswith("mcp__")))
    for k, (t, tools) in enumerate(snaps):
        end = snaps[k + 1][0] if k + 1 < len(snaps) else float("inf")
        servers = defaultdict(lambda: [0, 0, 0])   # server: [tools, unused tools, unused tokens]
        for x in tools:
            name = str(x.get("name", ""))
            if name.startswith("mcp__"):
                srv = servers[name.split("__")[1]]
                srv[0] += 1
                if name not in used:
                    srv[1] += 1
                    srv[2] += s.tok(len(json.dumps(x)))
        for server, (n, unused, tokens) in servers.items():
            if unused:
                add(12, tokens * s.read_span(t, end),
                    f"{server}: {unused}/{n} tools never called, ~{tokens:,} tokens of definitions on every call")

    # 13. Unused skills/plugins: listed skills and agent types the session never invoked
    invoked = {str(u["input"].get("skill", "")).lstrip("/") for u in s.tool_uses.values() if u["name"] == "Skill"}
    invoked |= {m for p in s.prompts for m in re.findall(r"<command-name>/([\w:.-]+)</command-name>", p["text"])}
    agent_types = {str(u["input"].get("subagent_type", "")) for u in list(s.tool_uses.values()) + list(s.helper_tool_uses.values())
                   if u["name"] in AGENT_TOOLS}
    for t, a, _ in s.attachments:
        if a.get("type") == "skill_listing":
            entries = re.split(r"\n(?=- )", a.get("content", ""))
            unused = [x for x in entries if x[2:].split(":", 1)[0] not in invoked]
            findings["_listing_sessions"].append(s.sid)
            if unused:
                add(13, s.carry(t, s.tok(sum(map(len, unused)))),
                    f"{len(unused)}/{len(entries)} listed skills never invoked (~{s.tok(sum(map(len, unused))):,} tokens)")
        elif a.get("type") == "agent_listing_delta":
            unused = [l for l in a.get("addedLines") or [] if l[2:].split(":", 1)[0] not in agent_types]
            if unused:
                add(13, s.carry(t, s.tok(sum(map(len, unused)))),
                    f"{len(unused)} listed agent types never used (~{s.tok(sum(map(len, unused))):,} tokens)")

    # 18. High effort on trivial turns: a turn answered in one short reply with no tool calls,
    # whose output tokens (which include reasoning) far exceed the reply itself
    prompt_times = [p["t"] for p in s.prompts]
    turn_calls = defaultdict(list)
    for c in s.calls:
        turn_calls[bisect.bisect_right(prompt_times, c["t"])].append(c)
    for calls in turn_calls.values():
        c = calls[0]
        think = sum(len(b.get("thinking", "")) for b in c["blocks"] if b.get("type") == "thinking")
        findings["_thinking"].append(s.tok(think, c["model"]))
        if len(calls) != 1 or c["n_tools"]:
            continue
        reply = s.tok(sum(len(b.get("text", "")) for b in c["blocks"] if b.get("type") == "text"), c["model"])
        reasoning = c["out"] - reply
        if reply <= TRIVIAL_TEXT and reasoning > THINK_LIMIT:
            add(18, (reasoning - THINK_BASELINE) * price(c["model"])[1] / 1e6,
                f"~{reasoning:,} reasoning tokens for a ~{reply:,}-token reply")

    # 20. Correction churn: work done in turns that start by correcting the previous answer
    for n, p in enumerate(s.prompts):
        if CORRECTION_RE.match(TAG_RE.sub("", p["text"], count=1)):
            end = s.prompts[n + 1]["t"] if n + 1 < len(s.prompts) else float("inf")
            calls = [c for c in s.calls if p["t"] <= c["t"] < end]
            if calls:
                add(20, sum(c["cost"] for c in calls), f"correction turn, {len(calls)} calls of rework")

    # 21. Visual iteration loops: edit -> screenshot cycles in one task, beyond the limit
    for tsk in tasks:
        cycles, edited = [], False
        for r in results:
            if not tsk["start"] <= r["t"] < tsk["end"]:
                continue
            name = r["name"] or ""
            if name in EDIT_TOOLS or name.endswith("__use_figma"):
                edited = True
            elif edited and (r["image_tokens"] or "screenshot" in name.lower()):
                cycles.append(r["t"])
                edited = False
        for k in range(VISUAL_LIMIT, len(cycles)):
            add(21, sum(c["cost"] for c in tsk["calls"] if cycles[k - 1] < c["t"] <= cycles[k]),
                f"edit -> screenshot cycle {k + 1} in one task")

    # inputs for the cross-session leaks (15, 22)
    edits = [r["t"] for r in results if r["name"] in EDIT_TOOLS]
    s.first_edit = first_edit = edits[0] if edits else float("inf")
    s.explore, seen = [], set()
    for r in results:
        path = r["input"].get("file_path", "")
        if r["name"] == "Read" and path and r["t"] < first_edit and path not in seen:
            seen.add(path)
            s.explore.append((path, r["tokens"], r["t"]))
    first_typed = next((p["text"] for p in s.prompts if not p["text"].lstrip().startswith("<")), "")
    s.first_words = prompt_words(first_typed)

    leak_extra.analyse(s, tasks, add, price, cache_cost)   # the canvas's "Additional categories" (A rows)
    findings["_sessions"].append(s)


def cross_session(findings):
    """Leaks that need several sessions of the same project: 15, 22 and some A rows."""
    leak_extra.cross_session(findings["_sessions"], lambda leak, s, cost, detail: add_finding(findings, leak, s, cost, detail))
    by_project = defaultdict(list)
    for s in findings["_sessions"]:
        by_project[s.project].append(s)
    for ss in by_project.values():
        ss.sort(key=lambda s: s.calls[0]["t"])
        explored, earlier = defaultdict(int), []
        for s in ss:
            # 22. Re-learning the codebase: exploring files that earlier sessions already explored
            hits = [(p, n, t) for p, n, t in s.explore if explored[p] >= RELEARN_MIN]
            if hits:
                add_finding(findings, 22, s, sum(s.carry(t, n) for _, n, t in hits),
                            f"{len(hits)} files re-read before the first edit that {RELEARN_MIN}+ earlier sessions also explored")
            for p, _, _ in s.explore:
                explored[p] += 1
            # 15. Repeated tasks across sessions: the same first request as an earlier session
            if len(s.first_words) < 5:
                continue
            match = next((e for e in earlier
                          if len(s.first_words & e.first_words) / len(s.first_words | e.first_words) >= REPEAT_SIM), None)
            if match:
                day = datetime.fromtimestamp(match.calls[0]["t"], timezone.utc).date()
                add_finding(findings, 15, s, s.cost + s.helper_cost,
                            f"first request matches session {match.sid[:8]} from {day}")
            earlier.append(s)

# ------------------------------------------------------------------ report


def unmeasurable(k, findings):
    """Why leak k can't be costed from this data, or None. Shown instead of a misleading $0.00."""
    if k == 12 and not findings["_snapshot_sessions"] or k == 13 and not findings["_listing_sessions"]:
        return NOT_RECORDED[k]
    if k == 10 and not findings["_hook_sessions"]:
        return "unmeasurable without hook data (see #11)"
    if k == 11:
        return "coverage gap, not a cost: waste in uncovered sessions is unknown"
    if k == 6 and UNITS == "tokens":
        return "a model choice, not a token count: a smaller model reads the same tokens"
    return None


def note_for(k, findings, total, sessions):
    if k in PARENT:
        return f"part of #{PARENT[k]}"
    if k == 12:
        have = len(findings["_snapshot_sessions"])
        mcp = findings["_mcp_tokens"]
        return (f"part of #1; {have}/{len(sessions)} sessions record their tools, median ~{int(statistics.median(mcp)):,} "
                "tokens of MCP definitions per session") if mcp else "part of #1"
    if k == 13:
        return "part of #1"
    if k == 4:
        return "spend to review, not all waste"
    if k == 15:
        return "spend to review: the earlier attempt may have failed"
    if k == 11:
        have = len(set(findings["_hook_sessions"]))
        return f"{have}/{len(sessions)} sessions have hook data (categories, ratings, idle detection)"
    if k == 8:
        out = sum(findings["_output_cost"])
        return f"all output is {out / total:.1%} of spend" if total else ""
    if k == 1 and findings["_prefix_sizes"]:
        return f"median starting context ~{int(statistics.median(findings['_prefix_sizes'])):,} tokens"
    if k == 2 and findings["_compactions"]:
        return f"{sum(findings['_compactions'])} compactions"
    if k == 6:
        main = sum(findings["_main_cost"])
        return f"{sum(findings['_top_tier_cost']) / main:.0%} of main-session spend on Opus/Fable" if main else ""
    if k == 18:
        visible = [t for t in findings["_thinking"] if t]
        return f"median visible thinking ~{int(statistics.median(visible)):,} tokens/turn" if visible else ""
    if k == 14:
        return "assumes screenshots stay in context until compaction"
    if k == 19:
        return "the summary call's input is not in transcripts"
    return ""


def additional_table(findings, total, w, examples_for=10):
    """Table of the canvas's additional categories; returns example lists for the costliest rows."""
    rows = []
    for n, (name, group, reason) in leak_extra.ADDITIONAL.items():
        items = findings.get(lid(n), [])
        rows.append((n, name, group, reason, sum(i["cost"] for i in items), items))
    measured = [r for r in rows if not r[3] and r[0] not in leak_extra.SAME_AS]
    w(f"\n## Additional categories\n")
    w(f"The canvas's other {len(rows)} categories, labelled A<canvas row>: {len(measured)} measured, "
      f"{len(leak_extra.SAME_AS)} measured by a core row, {len(rows) - len(measured) - len(leak_extra.SAME_AS)} unmeasurable.\n")
    w("| # | Leak | Category | Est. cost | Share of spend | Instances | Note |")
    w("|---|---|---|---|---|---|---|")
    order = lambda r: (2 if r[3] else 1 if r[0] in leak_extra.SAME_AS else 0, -r[4], r[0])
    for n, name, group, reason, cost, items in sorted(rows, key=order):
        if reason:
            w(f"| A{n} | {name} | {group} | unmeasurable | - | - | {reason} |")
        elif n in leak_extra.SAME_AS:
            label = LEAKS[leak_extra.SAME_AS[n]][0]
            w(f"| A{n} | {name} | {group} | see #{label} | - | - | same measure as #{label} |")
        else:
            share = f"{cost / total:.1%}" if total else "-"
            note = "spend to review, not all waste" if n in leak_extra.REVIEW else ""
            w(f"| A{n} | {name} | {group} | {fmt_cost(cost)} | {share} | {len(items)} | {note} |")
    costly = sorted((r for r in measured if r[5]), key=lambda r: -r[4])[:examples_for]
    return [(f"A{n}", name, items) for n, name, group, reason, cost, items in costly]


def report(findings, md_path=None, top=3, show_all=False, core_only=False):
    sessions = findings["_sessions"]
    total = sum(s.cost + s.helper_cost for s in sessions)
    lines = []
    w = lines.append
    days = sorted({datetime.fromtimestamp(c["t"], timezone.utc).date() for s in sessions for c in s.calls})
    w(f"# Token leak report\n")
    size = f"{total / 1e6:,.1f}M tokens processed" if UNITS == "tokens" else f"API-equivalent spend ${total:,.2f}"
    w(f"{len(sessions)} sessions, {days[0]} to {days[-1]}, {size}\n" if days else "no data\n")
    if UNITS == "tokens":
        w("Every token counts as 1. Cache categories are cache events: the tokens written to cache, not extra tokens.\n")
    cal = findings["_calibration"]
    if cal:
        own = sum(1 for _, n in cal if n)
        w(f"Item sizes (tool results, prompts, injected text) are estimated at {statistics.median(r for r, _ in cal):.2f} "
          f"characters per token (median). {own}/{len(cal)} sessions measured their own ratio from their tool results; "
          f"the rest use the tokenizer default. Per-call totals are exact.\n")
    if show_all:
        examples = legacy_tables(findings, total, sessions, w, core_only)
    else:
        examples = curated_table(findings, total, sessions, w)
    for label, name, items in examples:
        items = sorted(items, key=lambda i: -i["cost"])[:top]
        if items:
            w(f"\n## {label}. {name}: largest examples")
            for i in items:
                w(f"- {fmt_cost(i['cost'])}  {i['project']} / session {i['session']}: {i['detail']}")
    text = "\n".join(lines)
    print(text)
    if md_path:
        with open(md_path, "w") as f:
            f.write(text + "\n")
        print(f"\nwrote {md_path}")


def merged_items(sources, findings):
    """Findings of a curated row. A tool result flagged by several of its sources counts once,
    under the source that charged it most; findings without a ref are kept as they are."""
    items, by_ref = [], {}
    for k in sources:
        per_ref = defaultdict(list)
        for i in findings.get(k, []):
            if i.get("overlap"):
                continue
            if i.get("ref"):
                per_ref[i["ref"]].append(i)
            else:
                items.append(i)
        for ref, group in per_ref.items():
            cost = sum(i["cost"] for i in group)
            if ref not in by_ref or cost > by_ref[ref][0]:
                by_ref[ref] = (cost, group)
    return items + [i for cost, group in by_ref.values() for i in group]


def curated_rows(findings, total, sessions):
    """The 50 categories of leak_categories.py as (n, name, group, cost, items, reason, note), sorted
    as the report shows them. reason is set when the row can't be costed from this data."""
    rows = []
    for n, (name, group, sources) in leak_categories.CATEGORIES.items():
        items = merged_items(sources, findings)
        core = sources[0] if sources[0] in LEAKS and sources[0] not in PARENT else None
        reason = unmeasurable(core, findings) if core else None
        note = note_for(core, findings, total, sessions) if core else ""
        if not note and n in leak_categories.REVIEW:
            note = "spend to review, not all waste"
        if UNITS == "tokens" and n in leak_categories.CACHE_EVENTS:
            note = "cache event: tokens written, not extra tokens"
        rows.append((n, name, group, sum(i["cost"] for i in items), items, reason, note))
    rows.sort(key=lambda r: (r[5] is not None, -r[3], r[0]))
    return rows


def curated_table(findings, total, sessions, w):
    """The 50 categories of leak_categories.py; returns example lists for the costliest rows."""
    w("| # | Leak | Group | Est. cost | Share of spend | Instances | Note |")
    w("|---|---|---|---|---|---|---|")
    rows = curated_rows(findings, total, sessions)
    for n, name, group, cost, items, reason, note in rows:
        if reason:
            w(f"| {n} | {name} | {group} | unmeasurable | - | - | {'; '.join(x for x in (reason, note) if x)} |")
            continue
        share = f"{cost / total:.1%}" if total else "-"
        w(f"| {n} | {name} | {group} | {fmt_cost(cost)} | {share} | {len(items)} | {note} |")
    w("\nCosts overlap (a leaked tool result inside a never-ending session counts in both), so do not add them up. "
      "Run with --all for the full canvas list.\n")
    costly = [r for r in rows if r[4] and not r[5]][:leak_categories.EXAMPLE_ROWS]
    return [(str(n), name, items) for n, name, group, cost, items, reason, note in costly]


def legacy_tables(findings, total, sessions, w, core_only):
    """The full canvas list (--all): core leaks, then the additional categories unless core_only."""
    w("| # | Leak | Category | Est. cost | Share of spend | Instances | Note |")
    w("|---|---|---|---|---|---|---|")
    rows = []
    for k, (label, name, group) in LEAKS.items():
        items = findings.get(k, [])
        rows.append((k, label, name, group, sum(i["cost"] for i in items), len(items)))
    rows.sort(key=lambda r: (unmeasurable(r[0], findings) is not None, -r[4]))
    for k, label, name, group, cost, n in rows:
        note = note_for(k, findings, total, sessions)
        reason = unmeasurable(k, findings)
        if reason:
            w(f"| {label} | {name} | {group} | unmeasurable | - | - | {'; '.join(x for x in (reason, note) if x)} |")
            continue
        share = f"{cost / total:.1%}" if total else "-"
        w(f"| {label} | {name} | {group} | {fmt_cost(cost)} | {share} | {n} | {note} |")
    w("\nCosts overlap (a leaked tool result inside a never-ending session counts in both), so do not add them up.\n")
    examples = [(label, name, findings.get(k, [])) for k, label, name, group, cost, n in rows]
    if not core_only:
        examples += additional_table(findings, total, w)
    return examples


def main():
    ap = argparse.ArgumentParser(description="Rank Claude Code token leaks by estimated cost")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--events", default=os.path.expanduser("~/.claude/metrics/events.jsonl"))
    ap.add_argument("--since", help="YYYY-MM-DD")
    ap.add_argument("--days", type=int, help="only the last N days (instead of --since)")
    ap.add_argument("--ttl", choices=["5m", "1h"], default="1h",
                    help="cache lifetime: 1h on subscriptions, 5m on API keys or usage credits. Cache writes are "
                         "priced by the lifetime the transcript records; this is the fallback and sets break detection")
    ap.add_argument("--units", choices=["usd", "tokens"], default="usd",
                    help="usd: API list prices (default); tokens: every token counts as 1")
    ap.add_argument("--md", help="also write the report as Markdown")
    ap.add_argument("--top", type=int, default=3, help="examples shown per leak")
    ap.add_argument("--all", action="store_true", dest="show_all",
                    help="the full canvas list (core leaks and all additional categories) instead of the 50 categories")
    ap.add_argument("--core", action="store_true", help="with --all: only the core leaks, without the additional categories")
    a = ap.parse_args()
    set_units(a.units)
    since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp() if a.since else 0
    if a.days:
        since = datetime.now(timezone.utc).timestamp() - a.days * 86400
    ttl_s, write_mult = (300, 1.25) if a.ttl == "5m" else (3600, 2.0)
    hook_prompts, _ = load_hook_prompts(a.events)
    findings = defaultdict(list)
    for sid, entries in load_sessions(a.root, since).items():
        analyse(Session(sid, entries, write_mult, ttl_s, hook_prompts), findings)
    if not findings["_sessions"]:
        print(f"no sessions found under {a.root}")
        return
    cross_session(findings)
    report(findings, a.md, a.top, a.show_all or a.core, a.core)


if __name__ == "__main__":
    main()
