"""
prompt_check.py - a model labels a person's own prompt text for the prompt-based leak categories
(unrelated task in a long thread, correction, could have continued an earlier session, repeated task).

It runs `claude -p` with the person's Claude Code login. Prompt text goes to the model only; the cache
(prompt_checks.json in the metrics directory) holds labels keyed by a hash, never prompt text.
Results are cached, so re-runs are free. Never raises: on any failure the attributes stay "unknown" and
callers fall back to cheap heuristics.

label_sessions(sessions) sets on every session:
  s.prompt_labels   {index into s.prompts: {"new_task": bool, "correction": bool}}  (missing = unknown)
  s.first_match     None (unknown) or {"continues": sid|None, "repeats": sid|None}
  s.model_verdicts  {index into s.prompts: {"smaller_ok": bool, "reason": str}}  (missing = unknown): the model
                    judge's view of whether the next model down could have done that turn, from s.model_turns
"""
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import leak_config

VERSION = 1                      # bump to invalidate cached labels when the prompts below change
CHUNK = 40                       # typed prompts per call
PROMPT_CHARS = 500
CAND_CHARS = 400
MAX_CANDS = 8
JUDGE_CHUNK = 15                 # turns per judge call
REPLY_CHARS = 300
WORD_RE = re.compile(r"[a-z0-9_]{3,}")

SYSTEM_LABEL = (
    "You label prompts that one person typed to a coding assistant during one session. "
    "The prompts are numbered in order. For every prompt you are asked to label, decide two things.\n"
    "new_task: true when the prompt starts work unrelated to what the previous prompts were about "
    "(a different feature, a different bug, a different topic). False when it continues, refines, "
    "follows up on or builds on the earlier work (building an API and then its UI is related).\n"
    "correction: true when it rejects or corrects the previous answer or action (it was wrong, not what "
    "was asked, undo it, do it again differently). False for a new instruction or a preference given up "
    "front (\"don't use semicolons\" at the start of a task), a question, or approval.\n"
    "Reply with only a JSON object, no other text: "
    "{\"labels\":[{\"i\":2,\"new_task\":true,\"correction\":false}]} with one entry per prompt you are "
    "asked to label, where i is the number shown."
)

SYSTEM_MATCH = (
    "You compare the first prompt of a new coding-assistant session with earlier sessions from the same "
    "project. Each earlier session is numbered and shows how many hours before the new session started it was last active, its first prompt and its last prompts.\n"
    "continues: the number of the earlier session whose work the new first prompt directly continues "
    "(the same task, picking up where it left off), else null.\n"
    "repeats: the number of the earlier session whose first request asks for the same thing again, else null. "
    "Generic templates (\"continue\", \"review the PR\", \"run the tests\") that do not name the same work "
    "give null.\n"
    "Reply with only a JSON object, no other text: {\"continues\":3,\"repeats\":null}"
)


def _typed(s):
    """[(index into s.prompts, stripped text)] for prompts the person typed."""
    out = []
    for i, p in enumerate(getattr(s, "prompts", None) or []):
        t = (p.get("text") or "").strip()
        if t and not t.startswith("<"):
            out.append((i, t))
    return out


def _cut(t, n):
    return t if len(t) <= n else t[:n] + "..."


def _words(t):
    return set(WORD_RE.findall(t.lower()))


def _start(s):
    calls = getattr(s, "calls", None)
    return calls[0]["t"] if calls else None


def _key(model, kind, text):
    h = hashlib.sha256()
    h.update(f"{VERSION}\0{model}\0{kind}\0{text}".encode("utf-8", "replace"))
    return h.hexdigest()


# ---- cache ---------------------------------------------------------------------------------------

def _cache_path():
    return os.path.join(leak_config.METRICS_DIR, "prompt_checks.json")


def _load_cache():
    try:
        with open(_cache_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(new):
    if not new:
        return
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        merged = _load_cache()      # another report or a background sync may have written meanwhile
        merged.update(new)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".prompt_checks.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(merged, f)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        pass


# ---- model call ----------------------------------------------------------------------------------

def _first_json(text):
    """The first {...} JSON object in text (models sometimes wrap it in code fences), or None."""
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def _valid_labels(o):
    if not isinstance(o, dict) or not isinstance(o.get("labels"), list):
        return None
    out = []
    for e in o["labels"]:
        if not (isinstance(e, dict) and type(e.get("i")) is int
                and isinstance(e.get("new_task"), bool) and isinstance(e.get("correction"), bool)):
            return None
        out.append({"i": e["i"], "new_task": e["new_task"], "correction": e["correction"]})
    return {"labels": out}


def _valid_match(o):
    if not isinstance(o, dict) or "continues" not in o or "repeats" not in o:
        return None
    for k in ("continues", "repeats"):
        v = o[k]
        if v is not None and type(v) is not int:
            return None
    return {"continues": o["continues"], "repeats": o["repeats"]}


SYSTEM_JUDGE = (
    "You review turns from a developer's sessions with a coding assistant. Each turn shows the developer's prompt, "
    "the previous prompt for context, the model that handled it, and what it did: tool calls, lines edited, output "
    "and reasoning tokens, and the start of its final reply. Decide for each turn whether the smaller model named in "
    "the turn would have done it equally well.\n"
    "smaller_ok: true only for routine work: a simple question or lookup, running or reading commands, a small "
    "mechanical edit, a rename, formatting, boilerplate, or following explicit step-by-step instructions. "
    "False for debugging an unclear failure, design or architecture decisions, subtle correctness, concurrency or "
    "security work, reasoning across many files, ambiguous requirements, or anything where a mistake would be costly. "
    "A short prompt can still be hard (\"why does this deadlock?\"); a long one can still be routine. When unsure, false.\n"
    "reason: at most 12 words, about the work, not the person.\n"
    "Reply with only a JSON object, no other text: "
    "{\"verdicts\":[{\"i\":1,\"smaller_ok\":false,\"reason\":\"debugging an intermittent race across two services\"}]} "
    "with one entry per turn, where i is the number shown."
)


def _valid_verdicts(o):
    if not isinstance(o, dict) or not isinstance(o.get("verdicts"), list):
        return None
    out = []
    for e in o["verdicts"]:
        if not (isinstance(e, dict) and type(e.get("i")) is int and isinstance(e.get("smaller_ok"), bool)):
            return None
        out.append({"i": e["i"], "smaller_ok": e["smaller_ok"], "reason": str(e.get("reason") or "")[:120]})
    return {"verdicts": out}


VALIDATORS = {"label": _valid_labels, "match": _valid_match, "judge": _valid_verdicts}
SYSTEMS = {"label": SYSTEM_LABEL, "match": SYSTEM_MATCH, "judge": SYSTEM_JUDGE}


def _call(binary, model, kind, text, timeout):
    """Ask the model; the parsed, validated result, or None on any failure."""
    try:
        env = dict(os.environ, CC_METRICS_OFF="1")      # the plugin's own hook ignores this child session
        r = subprocess.run(
            [binary, "-p", "--model", model, "--no-session-persistence", "--tools", "",
             "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", "",
             "--output-format", "json", "--system-prompt", SYSTEMS[kind]],
            input=text, capture_output=True, text=True, timeout=timeout, env=env,
            cwd=tempfile.gettempdir())
        if r.returncode != 0:
            return None
        out = json.loads(r.stdout)
        if not isinstance(out, dict) or out.get("is_error") or not isinstance(out.get("result"), str):
            return None
        obj = _first_json(out["result"])
        return VALIDATORS[kind](obj) if obj is not None else None
    except Exception:
        return None


# ---- jobs ----------------------------------------------------------------------------------------

def _label_jobs(s, typed):
    """One job per chunk of typed prompts. Typed prompt k (1-based) is shown as [k]."""
    jobs = []
    n = len(typed)
    lo = 2
    while lo <= n:
        hi = min(n, lo + CHUNK - 1 - (1 if lo > 2 else 0))
        first = lo - 1 if lo > 2 else 1          # a later chunk shows the previous prompt as context
        lines = [f"[{k}] {_cut(typed[k - 1][1], PROMPT_CHARS)}" for k in range(first, hi + 1)]
        head = f"Label prompts {lo} to {hi}."
        if first < lo:
            head = f"Prompt {first} is context only. " + head
        else:
            head = "Prompt 1 is the start of the session. " + head
        jobs.append({"kind": "label", "text": head + "\n\n" + "\n\n".join(lines), "s": s,
                     "typed": typed, "lo": lo, "hi": hi})
        lo = hi + 1
    return jobs


def _match_job(s, typed, sessions_by_proj, info):
    t0 = _start(s)
    mine = [x for x in sessions_by_proj if x is not s and info[id(x)][0] is not None
            and info[id(x)][0] < t0 and _typed(x)]
    window = float(leak_config.CONFIG.get("restart_window_h", 24)) * 3600
    recent = [x for x in mine if 0 <= t0 - info[id(x)][1] <= window]
    recent.sort(key=lambda x: info[id(x)][1], reverse=True)
    cands = recent[:5]
    my_words = _words(typed[0][1])
    rest = []
    for x in mine:
        if x in cands:
            continue
        w = info[id(x)][2]
        union = my_words | w
        j = len(my_words & w) / len(union) if union else 0.0
        if j > 0.2:
            rest.append((j, x))
    rest.sort(key=lambda p: p[0], reverse=True)
    cands += [x for _, x in rest[:5]]
    cands = cands[:MAX_CANDS]
    if not cands:
        return None
    parts = ["New session's first prompt:\n" + _cut(typed[0][1], PROMPT_CHARS), "Earlier sessions:"]
    for n, x in enumerate(cands, 1):
        ty = _typed(x)
        hours = max(0.0, t0 - info[id(x)][1]) / 3600
        last = "\n".join(f"  - {_cut(t, CAND_CHARS)}" for _, t in ty[-3:])
        parts.append(f"[{n}] last active {hours:.1f} hours before the new session started\n"
                     f"first prompt: {_cut(ty[0][1], CAND_CHARS)}\nlast prompts:\n{last}")
    return {"kind": "match", "text": "\n\n".join(parts), "s": s,
            "sids": [getattr(x, "sid", None) for x in cands]}


def _judge_jobs(s):
    """One job per chunk of the session's Opus/Sonnet turns (s.model_turns, built by leak_report.model_turns)."""
    jobs, turns = [], list(getattr(s, "model_turns", None) or [])
    for lo in range(0, len(turns), JUDGE_CHUNK):
        chunk, blocks = turns[lo:lo + JUDGE_CHUNK], []
        for n, t in enumerate(chunk, 1):
            tools = ", ".join(f"{name} x{k}" for name, k in t["tools"]) or "none"
            blocks.append(
                f"[{n}] model: {t['model']}; could {t['cheaper']} have done it?\n"
                f"previous prompt: {_cut(t['previous'].strip(), 200) or '(none, first prompt)'}\n"
                f"prompt: {_cut(t['text'].strip(), PROMPT_CHARS)}\n"
                f"did: tool calls {tools}; {t['lines']} lines edited in {t['files']} files; "
                f"{t['out']:,} output tokens, {t['think']:,} reasoning tokens"
                + ("; delegated to an agent or wrote a plan" if t["delegates"] else "") + "\n"
                f"reply starts: {_cut(' '.join(t['reply'].split()), REPLY_CHARS) or '(no text)'}")
        jobs.append({"kind": "judge", "text": "\n\n".join(blocks), "s": s, "turns": chunk})
    return jobs


def _apply(job, res):
    s = job["s"]
    if job["kind"] == "judge":
        for e in res["verdicts"]:
            if 1 <= e["i"] <= len(job["turns"]):
                s.model_verdicts[job["turns"][e["i"] - 1]["prompt"]] = {"smaller_ok": e["smaller_ok"], "reason": e["reason"]}
    elif job["kind"] == "label":
        typed = job["typed"]
        for e in res["labels"]:
            if job["lo"] <= e["i"] <= job["hi"]:
                s.prompt_labels[typed[e["i"] - 1][0]] = {"new_task": e["new_task"],
                                                         "correction": e["correction"]}
    else:
        sids = job["sids"]

        def pick(v):
            return sids[v - 1] if v is not None and 1 <= v <= len(sids) else None
        s.first_match = {"continues": pick(res["continues"]), "repeats": pick(res["repeats"])}


def label_sessions(sessions, cfg=None, log=sys.stderr):
    stats = {"enabled": False, "cached": 0, "called": 0, "failed": 0, "over_budget": 0}
    try:
        sessions = list(sessions)
        for s in sessions:
            s.prompt_labels = {}
            s.first_match = None
            s.model_verdicts = {}
    except Exception:
        return stats
    try:
        cfg = cfg if cfg is not None else leak_config.CONFIG
        model = str(cfg.get("prompt_check_model") or "sonnet")
        binary = shutil.which("claude")
        enabled = bool(cfg.get("prompt_check", True)) and bool(binary) \
            and os.environ.get("CC_METRICS_PROMPT_CHECK") != "0" and os.environ.get("CC_METRICS_OFF") != "1"
        stats["enabled"] = enabled

        info = {}                  # id(session) -> (start, end, first-prompt words)
        by_proj = {}
        for s in sessions:
            calls = getattr(s, "calls", None)
            if not calls:
                continue
            ty = _typed(s)
            info[id(s)] = (calls[0]["t"], calls[-1]["t"], _words(ty[0][1]) if ty else set())
            by_proj.setdefault(getattr(s, "project", None), []).append(s)

        jobs = []
        for s in sessions:
            if id(s) not in info:
                continue
            try:                   # one odd session must not stop the others
                typed = _typed(s)
                if len(typed) >= 2:
                    jobs += _label_jobs(s, typed)
                jobs += _judge_jobs(s)
                if typed and not getattr(s, "cut", False):
                    j = _match_job(s, typed, by_proj[getattr(s, "project", None)], info)
                    if j is None:
                        s.first_match = {"continues": None, "repeats": None}
                    else:
                        jobs.append(j)
            except Exception:
                continue

        cache = _load_cache()
        todo = []
        for j in jobs:
            j["key"] = _key(model, j["kind"], j["text"])
            res = cache.get(j["key"])
            if res is not None and VALIDATORS[j["kind"]](res) is not None:
                _apply(j, res)
                stats["cached"] += 1
            else:
                todo.append(j)
        if not todo or not enabled:
            return stats

        todo.sort(key=lambda j: info[id(j["s"])][0], reverse=True)       # newest sessions first
        budget = max(0, int(cfg.get("prompt_check_max_calls", 60)))
        run, stats["over_budget"] = todo[:budget], max(0, len(todo) - budget)
        if not run:
            return stats
        if log is not None:
            try:
                n = len({id(j["s"]) for j in run})
                print(f"prompt check: labelling {n} sessions with {model} "
                      f"(cached results are reused next time)", file=log)
            except Exception:
                pass
        timeout = float(cfg.get("prompt_check_timeout_s", 120))
        workers = max(1, int(cfg.get("prompt_check_workers", 4)))
        new = {}
        with concurrent.futures.ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(_call, binary, model, j["kind"], j["text"], timeout): j for j in run}
            for f in concurrent.futures.as_completed(futs):
                j = futs[f]
                try:
                    res = f.result()
                except Exception:
                    res = None
                stats["called"] += 1
                if res is None:
                    stats["failed"] += 1
                    continue
                new[j["key"]] = res
                _apply(j, res)
        _save_cache(new)
    except Exception:
        pass
    return stats
