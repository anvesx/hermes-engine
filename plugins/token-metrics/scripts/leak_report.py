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
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import leak_categories
import leak_config
import leak_extra
import prompt_check
from leak_extra import lid

CFG = leak_config.CONFIG

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
START_BASELINE = 10_000        # what a fresh agent's context is compared with when no better baseline exists
TASK_GAP_S = 30 * 60           # an unlabelled prompt after this much idle time may start a new task
FORK_EXTRA = 20_000            # a fork starts at least this far above a fresh agent
IMAGE_DEFAULT = 1_600          # tokens for an image whose size can't be read
TRIVIAL_TEXT = 300             # a reply this short, with no tool calls, is a trivial turn
THINK_BASELINE = 1_000         # reasoning tokens considered reasonable on a trivial turn
NO_PROGRESS_MIN = 2            # edit -> screenshot cycles without visible change before a task is flagged
REPEAT_SIM = 0.6               # first-prompt word overlap that counts as the same task (without the prompt check)
EDIT_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LS"}
EXPLORE_CMD = re.compile(r"(^|\|\s*|&&\s*|;\s*)(grep|rg|ag|find|ls|cat|head|tail|tree)\b")
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
    27: ("17a", "Unchanged command reruns", "Terminal, build, and test output"),
}
PARENT = {23: 4, 24: 4, 25: 4, 26: 3, 27: 17}
SPEND_NOT_WASTE = {10, 15}   # reported as spend to review or information, not counted as pure waste
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
    """A cache miss sends no extra tokens: the same tokens are written to the cache, or sent uncached, instead of read
    from it. So in token units the cache detectors report those tokens (a cache event), and in dollars the price difference."""
    return tokens if UNITS == "tokens" else usd


def table_header(third):
    unit = ("Tokens", "Share of tokens") if UNITS == "tokens" else ("Est. cost", "Share of spend")
    return f"| # | Leak | {third} | {unit[0]} | {unit[1]} | Instances | Note |"


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


class SessionMap(dict):
    """sid -> entries inside the window. `before` maps each session that started before the window to its earlier
    entries, which are parsed only to find where the session really started; nothing in them is charged."""
    before = {}


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
                    if t is None:
                        continue
                    sid = e.get("sessionId") or os.path.splitext(os.path.basename(path))[0]
                    e["_t"], e["_n"], e["_project"] = t, n, project
                    e["_helper"] = bool(e.get("isSidechain")) or helper_file
                    e["_agent"] = (path if helper_file else e.get("agentId") or "sidechain") if e["_helper"] else None
                    sessions[sid].append(e)
        except OSError:
            continue
    out = SessionMap()
    out.before = {}
    for sid, evs in sessions.items():
        evs.sort(key=lambda e: (e["_t"], e["_n"]))
        inside = [e for e in evs if e["_t"] >= since]
        if inside:
            out[sid] = inside
            if len(inside) < len(evs):
                out.before[sid] = [e for e in evs if e["_t"] < since]
    return out


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

PERSON = {"human", "typed", "suggestion_accepted", "queued"}
SOURCE_NAMES = {"task-notification": "task notification", "task_notification": "task notification",
                "peer": "message from another agent", "sdk": "SDK", "system": "system message"}


def prompt_source(e):
    """Where a user entry came from, as recorded by newer Claude Code versions: 'person', a source name, or None."""
    origin = e.get("origin") if isinstance(e.get("origin"), dict) else {}
    kind = e.get("turnOrigin") or origin.get("kind") or e.get("promptSource")
    if not kind:
        return None
    return "person" if kind in PERSON else SOURCE_NAMES.get(kind, str(kind))


def typed(p):
    """A prompt the person wrote (not a command wrapper, task notification or system message)."""
    return bool(p["text"].strip()) and not p["text"].lstrip().startswith("<")

# ------------------------------------------------------------------ per-session analysis


class Session:
    def __init__(self, sid, entries, write_mult, ttl_s, hook_prompts, before=None):
        self.sid, self.project = sid, entries[0]["_project"]
        self.write_mult, self.ttl_s = write_mult, ttl_s
        self.hook_prompts = hook_prompts
        self.calls, self.helper_calls = [], []      # assistant model calls
        self.agents = defaultdict(list)             # helper calls by agent
        self.prompts, self.tool_uses, self.results = [], {}, []
        self.helper_tool_uses, self.helper_results = {}, []
        self.compactions, self.summaries = [], []
        self.compact_trigger, self.compact_pre, self.cwd = {}, {}, None   # compaction time -> trigger, tokens before it
        self.interrupts, self.uuids = [], set()
        self.prompt_labels, self.first_match = {}, None   # set by prompt_check.label_sessions
        self.model_turns, self.model_verdicts = [], {}      # turns the model judge sees, and its verdicts by prompt index
        self.attachments, self.skill_bodies = [], []   # what Claude Code injected: (t, attachment, rendered chars)
        self._parse(entries)
        self._segments()
        self._calibrate()
        self._size_items()
        # A session that started before a --days/--since window: detectors that depend on how a session or agent
        # started use its real start, not the first call inside the window (which carries all the earlier history).
        early = Session(sid, before, write_mult, ttl_s, {}) if before else None
        self.cut = bool(early and early.calls)
        self.start_ctx = early.calls[0]["ctx"] if self.cut else (self.calls[0]["ctx"] if self.calls else 0)
        self.start_prompt = (early.prompts[0]["tokens"] if early.prompts else 0) if self.cut else \
            (self.prompts[0]["tokens"] if self.prompts else 0)
        self.agents_before = set(early.agents) if early else set()

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
        tur = e.get("toolUseResult") if isinstance(e.get("toolUseResult"), dict) else {}
        patch = tur.get("structuredPatch")
        original = tur.get("originalFile")
        return {"t": e["_t"], "id": b.get("tool_use_id"), "agent": e["_agent"],
                "chars": text_len(content), "images": images, "image_tokens": sum(n for _, n in images),
                "is_error": bool(b.get("is_error")),
                "error": bool(b.get("is_error")) or bool(ERROR_TEXT.search(txt[:600])),
                "denied": bool(e.get("toolDenialKind")) or "doesn't want to proceed" in txt[:300],
                # what the tool recorded: lines an edit changed, the file's size before it, the agent a report came from
                "patch_lines": sum(1 for h in patch if isinstance(h, dict) for l in h.get("lines") or []
                                   if isinstance(l, str) and l[:1] in "+-") if isinstance(patch, list) else None,
                "file_lines": len(original.splitlines()) if isinstance(original, str) else None,
                "write_type": tur.get("type"), "agent_id": tur.get("agentId"), "agent_tools": tur.get("totalToolUseCount"),
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
                    meta = e.get("compactMetadata") if isinstance(e.get("compactMetadata"), dict) else {}
                    self.compact_trigger[e["_t"]] = meta.get("trigger")
                    self.compact_pre[e["_t"]] = meta.get("preTokens") or 0
                continue
            if self.cwd is None and e.get("cwd") and not e["_helper"]:
                self.cwd = e["cwd"]
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
                        self.prompts.append({"t": e["_t"], "chars": len(body), "text": txt, "body": body, "docs": docs,
                                             "source": prompt_source(e)})
        # one compaction writes a boundary marker and a summary; count boundaries when present
        self.compactions = boundaries or [t for t, _ in self.summaries]

        for c in self.calls + self.helper_calls:
            u = c["usage"]
            c["in"] = u.get("input_tokens", 0) or 0
            c["cw"] = u.get("cache_creation_input_tokens", 0) or 0
            c["cr"] = u.get("cache_read_input_tokens", 0) or 0
            c["out"] = u.get("output_tokens", 0) or 0
            details = u.get("output_tokens_details")
            c["think"] = details.get("thinking_tokens") if isinstance(details, dict) else None   # exact, when recorded
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
        # an Agent tool result records the agent's id; its calls are keyed by transcript path or agentId
        self.agent_by_id = {}
        for key in self.agents:
            base = os.path.splitext(os.path.basename(str(key)))[0]
            self.agent_by_id[base[6:] if base.startswith("agent-") else str(key)] = key

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
        """Split the session where a prompt starts a new task: a [tag], the prompt check's label, or, for prompts
        it hasn't labelled, an idle gap followed by a prompt that names none of the files touched so far."""
        if hasattr(self, "_tasks"):
            return self._tasks
        out = []
        touched = sorted(((u["t"], os.path.splitext(os.path.basename(str(u["input"].get("file_path") or u["input"].get("path") or "")))[0].lower())
                          for u in self.tool_uses.values()), key=lambda x: x[0])
        for n, p in enumerate(self.prompts):
            tag = TAG_RE.match(p["text"])
            label = self.prompt_labels.get(n) if n else None
            if label is not None:
                new, by = label["new_task"], "check"
            else:
                i = bisect.bisect_left(self.call_times, p["t"])
                last_activity = self.call_times[i - 1] if i > 0 else (self.prompts[n - 1]["t"] if n else None)
                gap = last_activity is not None and p["t"] - last_activity >= TASK_GAP_S
                words = prompt_words(p["text"])
                refers = any(stem in words for t, stem in touched if t < p["t"] and len(stem) >= 4)
                new, by = gap and not refers and typed(p), "gap"   # a notification or command wrapper isn't a new task
            if not out or tag or new:
                out.append({"start": p["t"], "category": tag.group(1).lower() if tag else None, "prompt": n,
                            "prompt_tokens": p["tokens"], "by": "tag" if tag else (by if out else "start")})
        for n, tsk in enumerate(out):
            tsk["end"] = out[n + 1]["start"] if n + 1 < len(out) else float("inf")
            tsk["calls"] = [c for c in self.calls if tsk["start"] <= c["t"] < tsk["end"]]
        self._tasks = out
        return out


# ------------------------------------------------------------------ leak detectors


def add_finding(findings, leak, s, cost, detail, ref=None, overlap=False):
    """ref: the tool result a finding is about, so a curated row merging two detectors counts it once.
    overlap: also recorded under another leak; kept for --all, skipped in the curated rows."""
    findings[leak].append({"cost": cost, "session": s.sid[:8], "project": s.project, "detail": detail,
                           "ref": ref and f"{s.sid}:{ref}", "overlap": overlap})


def edit_lines(r):
    """Lines an edit changed: from the patch the tool recorded, else from its input."""
    inp = r["input"]
    if r["write_type"] == "create":
        return len(str(inp.get("content", "")).splitlines())
    if r["patch_lines"] is not None:
        return r["patch_lines"]
    return sum(len(str(inp.get(k, "")).splitlines()) for k in ("old_string", "new_string", "content"))


def inventory(s, prefix):
    """What the session loaded before its first call, from the attachments Claude Code records: tool definitions
    (built-in and MCP, by server), skill and agent listings, instruction files and the system prompt. Sizes are
    estimated from characters and scaled down so they never add up to more than the measured starting context.
    Returns the breakdown of the starting context; sets s.mcp_loaded, s.listed (name -> tokens) for 48/49."""
    parts, servers, listed = defaultdict(int), defaultdict(int), {}
    t0 = s.calls[0]["t"] if s.calls else float("inf")
    seen, s.has_snapshot, got_system = set(), False, False
    for t, a, rendered in s.attachments:
        kind = a.get("type")
        if t > t0 + 60:   # the first full tool snapshot is recorded just after the first call
            continue
        if kind == "prompt_snapshot":
            if a.get("tools") and not s.has_snapshot:
                s.has_snapshot = True
                for x in a["tools"]:
                    n = s.tok(len(json.dumps(x)))
                    name = str(x.get("name", ""))
                    if name.startswith("mcp__"):
                        parts["MCP tool definitions"] += n
                        servers[name.split("__")[1]] += n
                    else:
                        parts["built-in tools"] += n
            if a.get("systemPrompt") and not got_system:
                got_system = True
                parts["system prompt"] += s.tok(len(json.dumps(a["systemPrompt"])))
            continue
        if kind in seen:
            continue
        seen.add(kind)
        size = s.tok(rendered or len(json.dumps(a)))
        if kind == "skill_listing":
            for entry in re.split(r"\n(?=- )", a.get("content", "")):
                if entry.strip():
                    listed[entry[2:].split(":", 1)[0].strip()] = s.tok(len(entry))
            parts["skill and agent listings"] += size
        elif kind == "agent_listing_delta":
            for line in a.get("addedLines") or []:
                listed["agent:" + line[2:].split(":", 1)[0].strip()] = s.tok(len(line))
            parts["skill and agent listings"] += size
        elif kind == "instructions":
            parts["CLAUDE.md and memory"] += size
        elif kind in ("mcp_instructions_delta", "deferred_tools_delta"):
            parts["MCP instructions and deferred tool names"] += size
        elif t <= t0:
            parts["environment and reminders"] += size
    total = sum(parts.values())
    scale = min(1.0, prefix / total) if total else 1.0
    s.mcp_loaded = {k: int(v * scale) for k, v in servers.items()}
    s.listed = {k: int(v * scale) for k, v in listed.items()}
    s.mcp_used = {u["name"].split("__")[1] for u in list(s.tool_uses.values()) + list(s.helper_tool_uses.values())
                  if str(u["name"]).startswith("mcp__") and len(u["name"].split("__")) > 2}
    s.invoked = {str(u["input"].get("skill", "")).lstrip("/") for u in s.tool_uses.values() if u["name"] == "Skill"}
    s.invoked |= {m for p in s.prompts for m in re.findall(r"<command-name>/([\w:.-]+)</command-name>", p["text"])}
    s.invoked |= {"agent:" + str(u["input"].get("subagent_type", "")) for u in list(s.tool_uses.values()) + list(s.helper_tool_uses.values())
                  if u["name"] in AGENT_TOOLS}
    parts = {k: int(v * scale) for k, v in parts.items() if v}
    if total and prefix > total * scale:
        parts["other (messages, environment)"] = int(prefix - total * scale)
    return parts


def model_turns(s):
    """Turns (a typed prompt and the main calls it started) handled by Opus/Fable or Sonnet, with what they did:
    the input to the model judge and to #6. Sets s.model_turns."""
    by_call = defaultdict(list)
    for r in s.results:
        if r["call"]:
            by_call[id(r["call"])].append(r)
    prompt_times = [p["t"] for p in s.prompts]
    turns = defaultdict(list)
    for c in s.calls:
        turns[bisect.bisect_right(prompt_times, c["t"]) - 1].append(c)
    s.model_turns, prev = [], ""
    for k in sorted(turns):
        if k < 0 or not typed(s.prompts[k]):
            continue
        calls, model = turns[k], turns[k][0]["model"]
        cheaper_id = "claude-sonnet-5-5" if top_tier(model) else "claude-haiku-4-5" if "sonnet" in model.lower() else None
        text, prev_text, prev = s.prompts[k]["text"], prev, s.prompts[k]["text"]
        if not cheaper_id:
            continue
        uses = [b for c in calls for b in c["blocks"] if b.get("type") == "tool_use"]
        rs = [r for c in calls for r in by_call[id(c)]]
        last_text = next((b.get("text", "") for c in reversed(calls) for b in c["blocks"] if b.get("type") == "text" and b.get("text")), "")
        s.model_turns.append({
            "prompt": k, "text": text, "previous": prev_text, "model": model, "cheaper_id": cheaper_id,
            "cheaper": "Sonnet" if cheaper_id.startswith("claude-sonnet") else "Haiku", "calls": calls,
            "prompt_tokens": s.prompts[k]["tokens"], "out": sum(c["out"] for c in calls),
            "think": sum(c["think"] or 0 for c in calls), "n_tools": len(uses),
            "tools": Counter(str(b.get("name")) for b in uses).most_common(),
            "lines": sum(edit_lines(r) for r in rs if r["name"] in EDIT_TOOLS),
            "files": len({str(r["input"].get("file_path")) for r in rs if r["name"] in EDIT_TOOLS}),
            "delegates": any(b.get("name") in AGENT_TOOLS | {"ExitPlanMode"} for b in uses), "reply": last_text})
    return s.model_turns


def analyse(s: Session, findings):
    if not s.calls:
        return
    tasks = s.tasks()
    prefix = max(0, s.start_ctx - s.start_prompt)   # the session's real start, even if it began before the window
    results = sorted(s.results, key=lambda r: r["t"])
    labels = s.prompt_labels
    prompt_times = [p["t"] for p in s.prompts]

    def add(leak, cost, detail, ref=None, overlap=False):
        add_finding(findings, leak, s, cost, detail, ref, overlap)

    def prompt_end(n):
        return s.prompts[n + 1]["t"] if n + 1 < len(s.prompts) else float("inf")

    findings["_calibration"].append(s.calibration.get(s.main_model, (s.chars_per_token(), 0)))

    # 1. Heavy starting context: the part above the threshold, re-read on every call. The breakdown says where it
    # comes from; 12 and 13 (curated 48, 49) price parts of the same tokens, so they are shown as part of #1.
    threshold = CFG["start_context_threshold"]
    parts = inventory(s, prefix)
    findings["_prefix_sizes"].append(prefix)
    if parts and not s.cut:
        findings["_start_parts"].append(parts)
    if prefix > threshold:
        top = max(parts.items(), key=lambda kv: kv[1]) if parts else None
        add(1, (prefix - threshold) * s.prefix_read[-1],
            f"starting context ~{prefix:,} tokens (threshold {threshold:,}) over {len(s.calls)} calls"
            + (f"; largest part {top[0]} ~{top[1]:,}" if top else ""))

    # 2. Sessions that never end: a prompt that starts an unrelated task while a large history is carried.
    # Flagged only when a session has several such switches.
    switches = []
    for tsk in tasks[1:]:
        if tsk["calls"]:
            carried = tsk["calls"][0]["ctx"] - prefix - tsk["prompt_tokens"]
            if carried > CFG["carry_min"]:
                switches.append((tsk, carried))
    findings["_switches"].append(len(switches))
    if len(switches) >= CFG["unrelated_switch_min"]:
        for tsk, carried in switches:
            how = {"tag": f"[{tsk['category']}] tag", "check": "unrelated prompt",
                   "gap": f"{TASK_GAP_S // 60}+ min gap, prompt names no earlier file"}.get(tsk["by"], tsk["by"])
            add(2, s.carry(tsk["start"], carried, until=tsk["end"]), f"new task ({how}) carried ~{carried:,} tokens of history")

    # 3. Losing the cache: large rewrites after the first call, with likely cause.
    # 3a. the ones after a break longer than the cache lifetime, read per write from the recorded 5m/1h split.
    # 19. Compaction cost: summary and rewrite of automatic compactions (a manual /compact between tasks is the cure).
    comp = s.comp_sorted
    compaction = {x: {"summary": 0, "rewrite": 0.0, "tokens": 0} for x in comp}
    for t, summary in s.summaries:
        k = bisect.bisect_right(comp, t + 5) - 1
        if k >= 0:
            compaction[comp[k]]["summary"] += summary
    lifetime = s.ttl_s
    for i in range(1, len(s.calls)):
        c, prev = s.calls[i], s.calls[i - 1]
        split = prev["usage"].get("cache_creation")
        if prev["cw"] and isinstance(split, dict):
            if split.get("ephemeral_1h_input_tokens"):
                lifetime = 3600
            elif split.get("ephemeral_5m_input_tokens"):
                lifetime = 300
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
            elif gap >= lifetime:
                cause = f"break of {gap / 60:.0f} min ({lifetime // 60}-min cache)"
                if c["cw"] >= CFG["break_rewrite_min"]:
                    add(26, premium, f"~{c['cw']:,} tokens rewritten, {cause}")
                    findings["_break_tokens"].append(c["cw"])
            else:
                event = next((x for x in s.prefix_events if prev["t"] < x[0] <= c["t"]), None)
                cause = event[1] if event else "context changed (tools, instructions, settings)"
                if event:
                    add(event[2], premium, f"~{c['cw']:,} tokens rewritten, {cause}")
            add(3, premium, f"~{c['cw']:,} tokens rewritten, {cause}")
    findings["_input_tokens"].append(sum(c["ctx"] for c in s.calls))
    auto = 0
    for x, cc in compaction.items():
        if s.compact_trigger.get(x) == "manual":
            continue
        auto += 1
        k = bisect.bisect_left(s.call_times, x) - 1
        out_price = price(s.calls[max(0, k)]["model"])[1]
        add(19, cc["summary"] * out_price / 1e6 + cc["rewrite"],
            f"automatic compaction: ~{cc['summary']:,} summary tokens written, ~{cc['tokens']:,} tokens rewritten after")
    findings["_auto_compacted"].append(auto)

    # 4. Many agents: spawns that cost more than doing the work in the main thread - an agent that made only a
    # couple of tool calls, or whose startup context is many times what it read.
    read_by_agent = defaultdict(int)
    for r in s.helper_results:
        read_by_agent[r["agent"]] += r["tokens"] + r["image_tokens"]
    spawns = low = 0
    for agent, calls in s.agents.items():
        if agent in s.agents_before or agent == "sidechain":   # started before the window, or not one agent
            continue
        spawns += 1
        tools = sum(c["n_tools"] for c in calls)
        start, read = calls[0]["ctx"], read_by_agent[agent]
        if tools < CFG["agent_min_tools"] or start > CFG["agent_startup_ratio"] * max(read, 1):
            low += 1
            add(4, sum(c["cost"] for c in calls),
                f"agent made {tools} tool calls and read ~{read:,} tokens; its startup alone was ~{start:,}")
    findings["_spawns"].append((spawns, low))

    # 4a. Fork context duplication: an agent that starts at roughly its parent's context, well above a fresh start
    starts = {a: calls[0]["ctx"] for a, calls in s.agents.items() if a not in s.agents_before}
    if starts:
        fresh = min(min(starts.values()), s.start_ctx or float("inf"))
        for agent, start in starts.items():
            calls = s.agents[agent]
            i = bisect.bisect_right(s.call_times, calls[0]["t"]) - 1
            parent = s.calls[i]["ctx"] if i >= 0 else 0
            if parent and start >= CFG["fork_share"] * parent and start - fresh > FORK_EXTRA:
                add(23, (start - fresh) * sum(c["read_price"] for c in calls),
                    f"agent started at ~{start:,} tokens, {start / parent:.0%} of its parent's context (fresh start ~{fresh:,})")

    # 4b. Overlapping agents: a file already read by a sibling agent, charged to the later reader (--all only)
    readers = defaultdict(set)
    for r in sorted(s.helper_results, key=lambda r: r["t"]):
        path = r["input"].get("file_path", "")
        if r["name"] != "Read" or not path:
            continue
        if readers[path] and r["agent"] not in readers[path]:
            add(24, s.agent_carry(r["agent"], r["t"], r["tokens"]),
                f"{os.path.basename(path)} also read by a sibling agent (~{r['tokens']:,} tokens)")
        readers[path].add(r["agent"])

    # 5. No clear direction: reads and searches before a task's first edit whose results were never used again -
    # the file is not named in any later reply or tool input, and a search found no file that was later opened.
    later = sorted([(c["t"], " ".join(b.get("text", "") for b in c["blocks"] if b.get("type") == "text")) for c in s.calls]
                   + [(u["t"], json.dumps(u["input"])) for u in s.tool_uses.values()], key=lambda x: x[0])
    later_times, offsets, pieces, pos = [x[0] for x in later], [], [], 0
    for _, txt in later:
        offsets.append(pos)
        pieces.append(txt.lower())
        pos += len(pieces[-1]) + 1
    later_text = "\n".join(pieces)
    opened = sorted((u["t"], os.path.basename(str(u["input"].get("file_path", "")))) for u in s.tool_uses.values()
                    if u["name"] in EDIT_TOOLS | {"Read"} and u["input"].get("file_path"))

    def used_after(r):
        if r["name"] == "Read" and r["input"].get("file_path"):
            i = bisect.bisect_right(later_times, r["t"])
            return i < len(later_times) and later_text.find(os.path.basename(r["input"]["file_path"]).lower(), offsets[i]) >= 0
        return any(t > r["t"] and name and name in r["body"] for t, name in opened)

    explored = dead_tokens = 0
    for tsk in tasks:
        rs = [r for r in results if tsk["start"] <= r["t"] < tsk["end"]]
        first_edit = next((r["t"] for r in rs if r["name"] in EDIT_TOOLS), None)
        if first_edit is None:   # investigations and reviews: the reading is the work
            continue
        dead = []
        for r in rs:
            if r["t"] >= first_edit:
                break
            cmd = str(r["input"].get("command", "")) if r["name"] == "Bash" else ""
            if r["name"] in EXPLORE_TOOLS or EXPLORE_CMD.search(cmd):
                explored += r["tokens"]
                if not used_after(r):
                    dead.append(r)
        dead_tokens += sum(r["tokens"] for r in dead)
        if len(dead) >= CFG["dead_end_min"]:
            add(5, sum(s.carry(r["t"], r["tokens"]) for r in dead),
                f"{len(dead)} reads/searches before the first edit never used again (~{sum(r['tokens'] for r in dead):,} tokens)")
    findings["_explore"].append((explored, dead_tokens))

    # 6. Bigger model than needed: an Opus/Fable or Sonnet turn the next model down could have done as well, priced
    # against that model. The model judge (prompt_check) decides from the prompt and what the turn did; turns it hasn't
    # judged use the size heuristic: short prompt, small output, few tool calls, tiny edits, little reasoning.
    n_turns = n_small = n_judged = 0
    for turn in s.model_turns or model_turns(s):
        n_turns += 1
        verdict = s.model_verdicts.get(turn["prompt"])
        if verdict is not None:
            n_judged += 1
            small, why = verdict["smaller_ok"], verdict["reason"]
        else:
            small = (turn["prompt_tokens"] <= CFG["small_prompt_tokens"] and turn["out"] <= CFG["small_output_tokens"]
                     and turn["n_tools"] <= CFG["small_tool_calls"] and turn["lines"] <= CFG["small_edit_lines"]
                     and turn["think"] <= CFG["small_thinking_tokens"] and not turn["delegates"])
            why = f"{turn['n_tools']} tool calls, {turn['lines']} lines edited (size heuristic)"
        if not small:
            continue
        n_small += 1
        if UNITS == "usd":   # a model-choice question: in tokens a smaller model reads the same
            pi, po, pr = PRICES[turn["cheaper_id"]]
            calls = turn["calls"]
            cheaper = sum((c["in"] * pi + c["cw"] * pi * c["wmult"] + c["cr"] * pr + c["out"] * po) / 1e6 for c in calls)
            add(6, sum(c["cost"] for c in calls) - cheaper, f"{turn['cheaper']} could have done this {turn['model']} turn: {why}")
    findings["_small_turns"].append((n_turns, n_small, n_judged))

    # 7. Too much tool output: duplicate reads, dependency-folder hits, oversized results.
    # Split out by source: 14 images, 16 failed calls, 17 shell output, 4c agent reports.
    big, keep = CFG["big_result"], CFG["big_keep"]
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
        # a non-zero exit is an ordinary shell result (a failing test before its fix); shell failures count as retries (#9)
        if r["is_error"] and "interrupted by user" not in r["text"] and name != "Bash":
            kind = ("denied by the user" if r["denied"] else "schema error" if SCHEMA_RE.search(r["text"])
                    else "wrong id/path" if WRONG_ID_RE.search(r["text"]) else "error")
            call = r["call"]
            wasted = call["out"] * price(call["model"])[1] / 1e6 / max(1, call["n_tools"]) if call else 0.0
            add(16, wasted + s.carry(r["t"], r["tokens"]), f"{name} {kind} (~{r['tokens']:,} tokens of error text)",
                ref=r["id"], overlap=r["denied"])   # a denial is the user's choice, not waste
            if kind == "schema error":
                add(lid(135), wasted + s.carry(r["t"], r["tokens"]), f"{name} rejected its arguments")
        if name == "Read" and path:
            key = (path, str(inp.get("offset")), str(inp.get("limit")))   # the model has sent a list as offset
            if key in seen_reads and path not in edited_since:
                add(7, s.carry(r["t"], r["tokens"]), f"re-read {os.path.basename(path)} (~{r['tokens']:,} tokens)",
                    overlap=True)
                add(lid(72), s.carry(r["t"], r["tokens"]), f"re-read {os.path.basename(path)} (~{r['tokens']:,} tokens)")
                continue
            seen_reads[key] = r["t"]
            edited_since.discard(path)
        if name in AGENT_TOOLS:
            # 4c. Verbose agent reports: a long report from an agent that read little (padding), not a long report
            # from a long investigation
            agent = s.agent_by_id.get(str(r["agent_id"])) if r["agent_id"] else None
            work = read_by_agent.get(agent) if agent in s.agents else None
            if work:
                findings["_report_ratio"].append(r["tokens"] / work)
            if r["tokens"] > CFG["report_big"]:
                padded = (r["tokens"] > CFG["report_work_ratio"] * work if work is not None
                          else isinstance(r["agent_tools"], int) and r["agent_tools"] < 5)
                if padded:
                    add(25, s.carry(r["t"], r["tokens"] - CFG["report_keep"]),
                        f"agent report ~{r['tokens']:,} tokens after reading ~{work or 0:,} "
                        f"({str(inp.get('description', ''))[:40] or name})")
            continue
        dep_lines = [l for l in r["text"].splitlines() if DEP_DIRS.search(l)]
        if name in ("Grep", "Glob", "Bash", "LS") and len(dep_lines) >= 5:
            dep_tokens = int(r["tokens"] * len(dep_lines) / max(1, len(r["text"].splitlines())))
            add(7, s.carry(r["t"], dep_tokens), f"{name} returned results from dependency/build folders ({len(dep_lines)}+ lines)",
                overlap=True)
            add(lid(76), s.carry(r["t"], dep_tokens), f"{name} returned results from dependency/build folders ({len(dep_lines)}+ lines)")
        elif r["tokens"] > big:
            what = os.path.basename(path) if path else (str(inp.get("command", ""))[:40] or name)
            add(17 if name == "Bash" else 7, s.carry(r["t"], r["tokens"] - keep),
                f"{name} result ~{r['tokens']:,} tokens ({what})", ref=r["id"])
        if name == "Bash":
            findings["_shell_tokens"].append(r["tokens"])

    # 8. Wordy responses: a Write over an existing file whose recorded patch changed only a small part of it
    # (an Edit would have written just that part)
    findings["_output_cost"].append(sum(c["out"] * price(c["model"])[1] / 1e6 for c in s.calls))
    for r in results:
        if r["name"] == "Write" and r["write_type"] == "update" and r["file_lines"] and r["patch_lines"] is not None and r["call"]:
            content = str(r["input"].get("content", ""))
            share = r["patch_lines"] / max(1, r["file_lines"] + len(content.splitlines()))
            if share <= CFG["rewrite_changed_share"]:
                written = s.tok(len(content), r["call"]["model"])
                add(8, written * (1 - share) * price(r["call"]["model"])[1] / 1e6,
                    f"rewrote {os.path.basename(str(r['input'].get('file_path', '')))} with Write to change ~{share:.0%} of it "
                    f"(~{written:,} tokens written)")

    # 9. Retry loops: the same tool call failing again with the same input. An edit in between makes a rerun a
    # test of the fix, not a retry.
    attempts = defaultdict(int)
    for r in results:
        if not r["call"]:
            continue
        if r["name"] in EDIT_TOOLS and not r["is_error"]:
            attempts.clear()
            continue
        key = (r["name"], hashlib.md5(json.dumps(r["input"], sort_keys=True).encode()).hexdigest())
        if r["is_error"] and not r["denied"] and "interrupted by user" not in r["text"]:
            attempts[key] += 1
            if attempts[key] >= 2:
                add(9, r["call"]["cost"] / max(1, r["call"]["n_tools"]),
                    f"{r['name']} failed {attempts[key]} times with the same input", ref=r["id"])
        else:
            attempts[key] = 0

    # 10. Usage while idle: turns not started by a person. Newer Claude Code versions record where each prompt came
    # from; older sessions fall back to hook data (prompts with no hook record within 15s were not typed).
    # Informational: a /loop or scheduled task may be exactly what the person set up.
    if any(p["source"] for p in s.prompts):
        for n, p in enumerate(s.prompts):
            if p["source"] not in (None, "person"):
                cost = sum(c["cost"] for c in s.calls if p["t"] <= c["t"] < prompt_end(n))
                if cost:
                    add(10, cost, f"turn started by a {p['source']}, not a person")
        findings["_origin_sessions"].append(s.sid)
    elif s.hook_prompts.get(s.sid) is not None:
        hook_typed = [e["ts"] for e in s.hook_prompts[s.sid]]
        covered_from = min(hook_typed) - 15
        for n, p in enumerate(s.prompts):
            if p["t"] >= covered_from and not any(abs(p["t"] - t) < 15 for t in hook_typed):
                cost = sum(c["cost"] for c in s.calls if p["t"] <= c["t"] < prompt_end(n))
                if cost:
                    add(10, cost, "turn started without a typed prompt (scheduled task, loop or background message)")
    if s.hook_prompts.get(s.sid) is not None:
        findings["_hook_sessions"].append(s.sid)

    # 12, 13 (MCP servers and skills rarely used) are judged across sessions in cross_session()
    if s.has_snapshot:
        findings["_snapshot_sessions"].append(s.sid)
    if s.listed:
        findings["_listing_sessions"].append(s.sid)

    # 18. High effort on trivial turns: one short reply, no tool calls, with recorded reasoning many times the reply
    turn_calls = defaultdict(list)
    for c in s.calls:
        turn_calls[bisect.bisect_right(prompt_times, c["t"])].append(c)
    for calls in turn_calls.values():
        c = calls[0]
        reply = s.tok(sum(len(b.get("text", "")) for b in c["blocks"] if b.get("type") == "text"), c["model"])
        reasoning = c["think"] if c["think"] is not None else c["out"] - reply
        findings["_thinking"].append(reasoning)
        if len(calls) != 1 or c["n_tools"]:
            continue
        if reply <= TRIVIAL_TEXT and reasoning > CFG["think_limit"] and reasoning >= CFG["think_ratio"] * max(reply, 1):
            add(18, (reasoning - THINK_BASELINE) * price(c["model"])[1] / 1e6,
                f"~{reasoning:,} reasoning tokens for a ~{reply:,}-token reply")

    # 20. Correction churn: a prompt that rejects the previous answer (the prompt check's label, else the keyword
    # pattern on a prompt that doesn't start a task). Only the work redone is charged: calls in the correction turn
    # that edit a file the previous turn edited, or revert an earlier edit.
    edits = sorted((u for u in s.tool_uses.values() if u["name"] in EDIT_TOOLS), key=lambda u: u["t"])
    task_starts = {tsk["prompt"] for tsk in tasks}
    n_typed = n_corr = 0
    last_typed = None
    for n, p in enumerate(s.prompts):
        if not typed(p):
            continue
        n_typed += 1
        label = labels.get(n)
        corr = label["correction"] if label is not None else (
            n not in task_starts and bool(CORRECTION_RE.match(TAG_RE.sub("", p["text"], count=1))))
        prev_start, last_typed = last_typed, p["t"]
        if not corr or prev_start is None:
            continue
        n_corr += 1
        before = {str(u["input"].get("file_path", "")): u for u in edits if prev_start <= u["t"] < p["t"]}
        undo = {(u["input"]["new_string"], u["input"]["old_string"]) for u in edits
                if u["t"] < p["t"] and isinstance(u["input"].get("old_string"), str) and isinstance(u["input"].get("new_string"), str)}
        redo = {id(u["call"]): u["call"] for u in edits if p["t"] <= u["t"] < prompt_end(n)
                and (str(u["input"].get("file_path", "")) in before
                     or (u["input"].get("old_string"), u["input"].get("new_string")) in undo)}
        if redo:
            add(20, sum(c["cost"] for c in redo.values()), f"correction: {len(redo)} calls redid edits from the previous turn")
    findings["_corrections"].append((n_typed, n_corr))

    # 21. Visual iteration loops: edit -> screenshot cycles that made no visible progress - the screenshot is the same
    # image as the previous cycle's, or the cycle's edit undid an earlier edit
    history = set()
    for tsk in tasks:
        cycles, edited, reverted, start = [], False, False, tsk["start"]
        for r in results:
            if not tsk["start"] <= r["t"] < tsk["end"]:
                continue
            name = r["name"] or ""
            if name in EDIT_TOOLS or name.endswith("__use_figma"):
                old, new = str(r["input"].get("old_string")), str(r["input"].get("new_string"))
                reverted = reverted or (r["input"].get("old_string") is not None and (new, old) in history)
                history.add((old, new))
                edited = True
            elif edited and (r["image_tokens"] or "screenshot" in name.lower()):
                cycles.append((start, r["t"], r["images"][0][0] if r["images"] else None, reverted))
                start, edited, reverted = r["t"], False, False
        stuck = [k for k, (_, _, h, rev) in enumerate(cycles) if rev or (k and h and h == cycles[k - 1][2])]
        if len(stuck) >= NO_PROGRESS_MIN:
            for k in stuck:
                t0, t1 = cycles[k][0], cycles[k][1]
                add(21, sum(c["cost"] for c in tsk["calls"] if t0 < c["t"] <= t1),
                    f"edit -> screenshot cycle {k + 1} made no visible change" + (" (edit undone)" if cycles[k][3] else ""))

    # inputs for the cross-session leaks (12, 13, 15, 22) and the A rows
    first_edit_t = [r["t"] for r in results if r["name"] in EDIT_TOOLS]
    s.first_edit = first_edit_t[0] if first_edit_t else float("inf")
    s.explore, seen = [], set()
    for r in results:
        path = r["input"].get("file_path", "")
        if r["name"] == "Read" and path and r["t"] < s.first_edit and path not in seen:
            seen.add(path)
            s.explore.append((path, r["tokens"], r["t"]))
    s.read_paths = {r["input"].get("file_path") for r in results if r["name"] == "Read" and r["input"].get("file_path")}
    s.edited = {r["input"].get("file_path") for r in results if r["name"] in EDIT_TOOLS and not r["is_error"] and r["input"].get("file_path")}
    first_typed = next((p["text"] for p in s.prompts if typed(p)), "")
    s.first_words = prompt_words(first_typed)
    notes = None   # project notes: a loaded project CLAUDE.md, else one in the working directory
    for t, a, _ in s.attachments:
        if a.get("type") == "instructions":
            notes = any(f.get("type") in ("Project", "Local") for f in a.get("files") or [])
            break
    if notes is None and s.cwd:
        notes = any(os.path.exists(os.path.join(s.cwd, x)) for x in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"))
    s.has_notes = notes

    leak_extra.analyse(s, tasks, add, price, cache_cost)   # the canvas's "Additional categories" (A rows)
    if s.long_parts:
        findings["_long_parts"].append(s.long_parts)
    findings["_sessions"].append(s)


def cross_session(findings):
    """Leaks that need several sessions: 12, 13, 15, 22 and some A rows."""
    sessions = findings["_sessions"]
    leak_extra.cross_session(sessions, lambda leak, s, cost, detail: add_finding(findings, leak, s, cost, detail))

    # 12. MCP tool schema bloat: servers loaded with full definitions (deferred tools aren't) but called in few of
    # the sessions that loaded them; charged in the sessions that loaded and didn't call them
    loaded, called = Counter(), Counter()
    for s in sessions:
        for srv in s.mcp_loaded:
            loaded[srv] += 1
            called[srv] += srv in s.mcp_used
    for s in sessions:
        for srv, tokens in s.mcp_loaded.items():
            if srv not in s.mcp_used and loaded[srv] >= 3 and called[srv] / loaded[srv] < CFG["rare_server_share"]:
                add_finding(findings, 12, s, tokens * s.prefix_read[-1],
                            f"{srv}: definitions loaded on every call (~{tokens:,} tokens), called in {called[srv]}/{loaded[srv]} sessions")

    # 13. Unused skills/plugins: listed skills and agent types not invoked in any session within N days either side
    invoked_at = defaultdict(list)
    for s in sessions:
        for name in s.invoked:
            invoked_at[name].append(s.calls[0]["t"])
    span = CFG["unused_skill_days"] * 86400
    for s in sessions:
        t0 = s.calls[0]["t"]
        unused = [tok for name, tok in s.listed.items() if not any(abs(t - t0) <= span for t in invoked_at.get(name, ()))]
        if unused:
            add_finding(findings, 13, s, sum(unused) * s.prefix_read[-1],
                        f"{len(unused)}/{len(s.listed)} listed skills and agent types unused within {CFG['unused_skill_days']} days "
                        f"(~{sum(unused):,} tokens)")

    by_sid = {s.sid: s for s in sessions}
    by_project = defaultdict(list)
    for s in sessions:
        by_project[s.project].append(s)
    window = CFG["relearn_days"] * 86400
    for ss in by_project.values():
        ss.sort(key=lambda s: s.calls[0]["t"])
        explored, earlier = defaultdict(list), []
        for s in ss:
            t0 = s.calls[0]["t"]
            # 22. Re-learning the codebase: exploring files that several recent sessions already explored
            if not s.cut:
                findings["_relearn"].append((s.has_notes, sum(n for _, n, _ in s.explore)))
                hits = [(p, n, t) for p, n, t in s.explore
                        if sum(1 for x in explored[p] if t0 - x <= window) >= CFG["relearn_min_sessions"]]
                if hits:
                    add_finding(findings, 22, s, sum(s.carry(t, n) for _, n, t in hits),
                                f"{len(hits)} files re-read before the first edit that {CFG['relearn_min_sessions']}+ recent sessions "
                                f"also explored" + ("" if s.has_notes else "; project has no CLAUDE.md"))
            for p, _, _ in s.explore:
                explored[p].append(t0)
            # 15. Repeated tasks across sessions: the same request as an earlier session (prompt check, else word
            # overlap) that edits mostly the same files again. Spend to review: the earlier attempt may have failed.
            match = None
            if not s.cut:
                if s.first_match is not None:
                    m = by_sid.get(s.first_match.get("repeats"))
                    match = m if m is not None and m.project == s.project and m.calls[0]["t"] < t0 else None
                elif len(s.first_words) >= 5:
                    match = next((e for e in earlier if len(s.first_words & e.first_words)
                                  / len(s.first_words | e.first_words) >= REPEAT_SIM), None)
            if match is not None and s.edited:
                overlap = len(s.edited & match.edited) / len(s.edited)
                if overlap >= CFG["repeat_edit_overlap"]:
                    day = datetime.fromtimestamp(match.calls[0]["t"], timezone.utc).date()
                    add_finding(findings, 15, s, s.cost + s.helper_cost,
                                f"same request as session {match.sid[:8]} from {day}, re-edited {overlap:.0%} of the same files")
            earlier.append(s)


def analyse_all(root, since, write_mult=2.0, ttl_s=3600, hook_prompts=None, log=sys.stderr):
    """Parse every session under root, label prompts (prompt_check), run every detector. Returns findings."""
    findings = defaultdict(list)
    loaded = load_sessions(root, since)
    sessions = [Session(sid, entries, write_mult, ttl_s, hook_prompts or {}, loaded.before.get(sid))
                for sid, entries in loaded.items()]
    for s in sessions:
        if s.calls:
            model_turns(s)
    findings["_prompt_check"] = [prompt_check.label_sessions([s for s in sessions if s.calls], log=log)]
    for s in sessions:
        analyse(s, findings)
    if findings["_sessions"]:
        cross_session(findings)
    return findings

# ------------------------------------------------------------------ report


def unmeasurable(k, findings):
    """Why leak k can't be costed from this data, or None. Shown instead of a misleading $0.00."""
    if k == 12 and not findings["_snapshot_sessions"] or k == 13 and not findings["_listing_sessions"]:
        return NOT_RECORDED[k]
    if k == 10 and not findings["_hook_sessions"] and not findings["_origin_sessions"]:
        return "unmeasurable: no prompt origins recorded and no hook data (see #11)"
    if k == 11:
        return "coverage gap, not a cost: waste in uncovered sessions is unknown"
    if k == 6 and UNITS == "tokens":
        return "a model choice, not a token count: a smaller model reads the same tokens"
    return None


def share(part, whole):
    return f"{part / whole:.0%}" if whole else "-"


def note_for(k, findings, total, sessions):
    f = findings
    if k == 1 and f["_prefix_sizes"]:
        sizes, thr = f["_prefix_sizes"], CFG["start_context_threshold"]
        parts = defaultdict(int)
        for p in f["_start_parts"]:
            for name, n in p.items():
                parts[name] += n
        whole = sum(parts.values())
        mix = ", ".join(f"{name} {n / whole:.0%}" for name, n in sorted(parts.items(), key=lambda kv: -kv[1])[:4]) if whole else ""
        return (f"median ~{int(statistics.median(sizes)):,} tokens; {share(sum(1 for x in sizes if x > thr), len(sizes))} of sessions "
                f"over {thr // 1000}k" + (f"; made of {mix}" if mix else ""))
    if k == 12:
        return f"part of #1; {len(set(f['_snapshot_sessions']))}/{len(sessions)} sessions record their tools (deferred tools excluded)"
    if k == 13:
        return "part of #1"
    if k == 2:
        sw = f["_switches"]
        return f"{sum(sw)} unrelated task switches carrying {CFG['carry_min'] // 1000}k+ tokens in {sum(1 for x in sw if x)} sessions"
    if k == 4:
        spawns, low = sum(x for x, _ in f["_spawns"]), sum(y for _, y in f["_spawns"])
        return f"{low}/{spawns} agent spawns low-value ({share(low, spawns)})" if spawns else ""
    if k == 5:
        explored, dead = sum(x for x, _ in f["_explore"]), sum(y for _, y in f["_explore"])
        return f"dead ends are {share(dead, explored)} of exploration tokens before first edits" if explored else ""
    if k == 6:
        turns, small, judged = (sum(x[i] for x in f["_small_turns"]) for i in range(3))
        return (f"{small}/{turns} Opus/Sonnet turns could have run on the next model down ({share(small, turns)}); "
                f"{judged} judged by a model, the rest by size") if turns else ""
    if k == 8:
        out = sum(f["_output_cost"])
        return f"all output is {out / total:.1%} of spend" if total else ""
    if k == 10:
        return "informational: turns started by agents, notifications, the SDK or the system; a /loop may be intended"
    if k == 11:
        have = len(set(f["_hook_sessions"]))
        return f"{have}/{len(sessions)} sessions have hook data (categories, ratings, idle detection)"
    if k == 15:
        return "spend to review: the earlier attempt may have failed"
    if k == 18:
        visible = [t for t in f["_thinking"] if t]
        return f"median reasoning ~{int(statistics.median(visible)):,} tokens/turn" if visible else ""
    if k == 19:
        auto = f["_auto_compacted"]
        return f"{share(sum(1 for x in auto if x), len(auto))} of sessions auto-compacted; supporting info for long history" if auto else ""
    if k == 20:
        typed_n, corr = sum(x for x, _ in f["_corrections"]), sum(y for _, y in f["_corrections"])
        return f"{share(corr, typed_n)} of prompts are corrections; only redone edits are charged" if typed_n else ""
    if k == 22:
        rows = f["_relearn"]
        with_n = [n for has, n in rows if has]
        without = [n for has, n in rows if has is False]
        if with_n and without:
            return (f"before the first edit, sessions without CLAUDE.md explored ~{int(statistics.mean(without)):,} tokens vs "
                    f"~{int(statistics.mean(with_n)):,} with; {share(len(without), len(rows))} of sessions have no project notes")
        return f"{share(len(without), len(rows))} of sessions have no project notes" if rows else ""
    if k == 25:
        ratios = f["_report_ratio"]
        return "part of #4" + (f"; median report is {statistics.median(ratios):.2f}x what the agent read" if ratios else "")
    if k == 26:
        tokens, whole = sum(f["_break_tokens"]), sum(f["_input_tokens"])
        return f"part of #3; ~{tokens / 1e6:,.1f}M tokens rewritten after breaks ({tokens / whole:.1%} of input tokens)" if whole else "part of #3"
    if k in PARENT:
        return f"part of #{PARENT[k]}"
    if k == 14:
        return "assumes screenshots stay in context until compaction"
    return ""


def curated_note(n, findings, total):
    """Notes for curated rows whose first source is not a core leak."""
    f = findings
    if n == 6 and f["_long_parts"]:
        parts = defaultdict(int)
        for p in f["_long_parts"]:
            for name, x in p.items():
                parts[name] += x
        whole = sum(parts.values())
        mix = ", ".join(f"{name} {x / whole:.0%}" for name, x in sorted(parts.items(), key=lambda kv: -kv[1]) if x)
        return f"{len(f['_long_parts'])} sessions flagged; at their peak the context was {mix}" if whole else ""
    if n == 25:
        shell = sum(f["_shell_tokens"])
        return f"repeated lines, tracebacks, lint output and reruns; {len(f['_shell_tokens'])} shell results, ~{shell / 1e6:,.1f}M tokens" if shell else ""
    if n == 24:
        return f"heuristic: results over {CFG['big_result']:,} tokens, the part over {CFG['big_keep']:,} (config)"
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
    w(table_header("Category"))
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
        w("Every token counts as 1. Cache categories are cache events: tokens that missed the cache (written to it or "
          "sent uncached), not extra tokens.\n")
    cal = findings["_calibration"]
    if cal:
        own = sum(1 for _, n in cal if n)
        w(f"Item sizes (tool results, prompts, injected text) are estimated at {statistics.median(r for r, _ in cal):.2f} "
          f"characters per token (median). {own}/{len(cal)} sessions measured their own ratio from their tool results; "
          f"the rest use the tokenizer default. Per-call totals are exact.\n")
    pc = (findings.get("_prompt_check") or [None])[0]
    if pc:
        multi = [s for s in sessions if sum(map(typed, s.prompts)) >= 2]
        labelled = sum(1 for s in multi if s.prompt_labels)
        w(f"Prompt check ({CFG['prompt_check_model']}{'' if pc['enabled'] else ', off: cached labels only'}): "
          f"{labelled}/{len(multi)} multi-prompt sessions labelled"
          + (f"; {pc['over_budget']} left for the next run" if pc.get("over_budget") else "")
          + ". Unlabelled prompts use keyword and file-overlap checks.\n")
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
    """The curated categories of leak_categories.py as (n, name, group, cost, items, reason, note), sorted
    as the report shows them. reason is set when the row can't be costed from this data."""
    rows = []
    for n, (name, group, sources) in leak_categories.CATEGORIES.items():
        items = merged_items(sources, findings)
        core = sources[0] if sources[0] in LEAKS else None
        reason = unmeasurable(core, findings) if core and core not in PARENT else None
        # core-leak notes say "part of #<core id>"; curated rows name their own parent below
        note = re.sub(r"^part of #\w+(; )?", "", note_for(core, findings, total, sessions)) if core else ""
        note = "; ".join(x for x in (curated_note(n, findings, total), note) if x)
        if n in leak_categories.PART_OF:
            note = "; ".join(x for x in (f"part of #{leak_categories.PART_OF[n]}", note) if x)
        if n in leak_categories.REVIEW and not re.search(r"review|informational", note):
            note = "; ".join(x for x in ("spend to review, not all waste", note) if x)
        if UNITS == "tokens" and n in leak_categories.CACHE_EVENTS:
            note = "cache event: tokens that missed the cache, not extra tokens"
        rows.append((n, name, group, sum(i["cost"] for i in items), items, reason, note))
    rows.sort(key=lambda r: (r[5] is not None, -r[3], r[0]))
    return rows


def curated_table(findings, total, sessions, w):
    """The curated categories: leaks first, then spend to review in its own table. Returns example lists for the
    costliest rows."""
    rows = curated_rows(findings, total, sessions)
    for title, part in (("", [r for r in rows if r[0] not in leak_categories.REVIEW]),
                        ("## Spend to review\n\nNormal spend that is sometimes avoidable; not counted as waste.\n",
                         [r for r in rows if r[0] in leak_categories.REVIEW])):
        if title:
            w(title)
        w(table_header("Group"))
        w("|---|---|---|---|---|---|---|")
        for n, name, group, cost, items, reason, note in part:
            if reason:
                w(f"| {n} | {name} | {group} | unmeasurable | - | - | {'; '.join(x for x in (reason, note) if x)} |")
                continue
            pct = f"{cost / total:.1%}" if total else "-"
            w(f"| {n} | {name} | {group} | {fmt_cost(cost)} | {pct} | {len(items)} | {note} |")
        w("")
    w("Costs overlap (a leaked tool result inside a never-ending session counts in both), so do not add them up. "
      "Rows marked \"part of #n\" price part of row n's tokens. Run with --all for the full canvas list.\n")
    costly = [r for r in rows if r[4] and not r[5]][:leak_categories.EXAMPLE_ROWS]
    return [(str(n), name, items) for n, name, group, cost, items, reason, note in costly]


def legacy_tables(findings, total, sessions, w, core_only):
    """The full canvas list (--all): core leaks, then the additional categories unless core_only."""
    w(table_header("Category"))
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
    findings = analyse_all(a.root, since, write_mult, ttl_s, hook_prompts)
    if not findings["_sessions"]:
        print(f"no sessions found under {a.root}")
        return
    report(findings, a.md, a.top, a.show_all or a.core, a.core)


if __name__ == "__main__":
    main()
