"""
leak_config.py - thresholds and switches for the leak detectors, overridable per person.

Defaults live here. To change one, put the key in config.json in the metrics directory
(~/.claude/metrics, or $CC_METRICS_DIR), e.g. {"start_context_threshold": 80000, "prompt_check": false}.
Unknown keys are ignored; a broken file falls back to the defaults.
"""
import json
import os

METRICS_DIR = os.environ.get("CC_METRICS_DIR") or os.path.expanduser("~/.claude/metrics")
PATH = os.path.join(METRICS_DIR, "config.json")

DEFAULTS = {
    # 01 Heavy starting context: starting context above this counts (Claude Code alone needs ~17k,
    # setups with deferred tools start at ~55k)
    "start_context_threshold": 60_000,
    # 48 MCP servers loaded with full definitions but called in fewer than this share of those sessions
    "rare_server_share": 0.2,
    # 49 listed skills not invoked in any session within this many days either side
    "unused_skill_days": 14,
    # 04 a rewrite after a break smaller than this is cheap and not flagged
    "break_rewrite_min": 10_000,
    # 05 a spawn is low-value with fewer tool calls than this, or a startup this many times what it read
    "agent_min_tools": 3,
    "agent_startup_ratio": 5,
    # 06 long history: average context above this share of the window, in a session with this many calls
    "long_context_share": 0.6,
    "long_session_min_calls": 50,
    "history_keep": 100_000,        # history a lean session carries; flagged sessions are charged above it
    "context_window": None,         # tokens; None infers 1M or 200k from the session's peak context
    # 08 an unrelated task switch carrying this much history; a session needs this many to be flagged
    "carry_min": 50_000,
    "unrelated_switch_min": 2,
    # 09 dead-end reads/searches before the first edit of a task, before the task is flagged
    "dead_end_min": 5,
    # 10 an earlier session this recent can be continued instead of starting fresh
    "restart_window_h": 24,
    # 12 a turn is a small task when all of these hold
    "small_prompt_tokens": 150,
    "small_output_tokens": 1_500,
    "small_tool_calls": 3,
    "small_edit_lines": 10,
    "small_thinking_tokens": 1_000,
    # 13 an agent starting at this share of its parent's context (and well above a fresh start) is a fork
    "fork_share": 0.8,
    # 24 Too much tool output
    "big_result": 4_000,
    "big_keep": 2_000,
    # 26 sessions repeating a request must also re-edit this share of the same files
    "repeat_edit_overlap": 0.5,
    # 36 a Write over an existing file that changed at most this share of its lines should have been an Edit
    "rewrite_changed_share": 0.3,
    # 42 agent report size, part kept as useful, and report tokens per token the agent read
    "report_big": 2_500,
    "report_keep": 1_000,
    "report_work_ratio": 0.5,
    # 44 files explored before the first edit in this many sessions within relearn_days
    "relearn_min_sessions": 3,
    "relearn_days": 30,
    # 45 short tool-free turns whose reasoning exceeds both of these
    "think_limit": 3_000,
    "think_ratio": 5,
    # prompt check (08, 10, 22, 26): a model labels prompt text; results are cached by prompt hash
    "prompt_check": True,
    "prompt_check_model": "sonnet",
    "prompt_check_max_calls": 60,    # new (uncached) model calls per run; the rest wait for the next run
    "prompt_check_workers": 4,
    "prompt_check_timeout_s": 120,
}


def load(path=PATH):
    cfg = dict(DEFAULTS)
    try:
        with open(path) as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


CONFIG = load()
