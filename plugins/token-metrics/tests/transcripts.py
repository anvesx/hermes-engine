"""Builds synthetic Claude Code transcripts for the tests: real JSONL files in a temp directory, read back
through leak_report.load_sessions so the tests exercise the same path as a real run."""
import json
import os
from datetime import datetime, timezone

MODEL = "claude-opus-4-8"
T0 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


class Transcript:
    """One session. Times are seconds after T0; each call's usage is given as its total context
    (all input) and output, so a test states the arithmetic it relies on."""

    def __init__(self, sid, model=MODEL, agent=None):
        """`agent` names a helper agent: every row is then a sidechain row of that agent."""
        self.sid, self.model, self.agent, self.rows, self.n = sid, model, agent, [], 0

    def _row(self, kind, t, message, **extra):
        self.n += 1
        if self.agent:
            extra = {"isSidechain": True, "agentId": self.agent, **extra}
        self.rows.append({"type": kind, "timestamp": iso(T0 + t), "sessionId": self.sid,
                          "uuid": f"{self.sid}-{self.agent or 'main'}-{self.n}", "message": message, **extra})

    def prompt(self, t, text="do the thing"):
        self._row("user", t, {"role": "user", "content": text})
        return self

    def call(self, t, ctx, out, tools=(), model=None, text="ok"):
        """An assistant call. `tools` are (tool_use id, tool name, input) triples."""
        content = [{"type": "text", "text": text}] + [
            {"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in tools]
        usage = {"input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": ctx,
                 "output_tokens": out}
        self._row("assistant", t, {"id": f"msg-{self.sid}-{self.agent or 'main'}-{self.n}", "role": "assistant",
                                   "model": model or self.model, "usage": usage, "content": content})
        return self

    def result(self, t, tool_id, text):
        self._row("user", t, {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_id, "content": text}]})
        return self

    def meta(self, t, text="<system-reminder>injected</system-reminder>", source_tool_use_id=None):
        """A message Claude Code injects on its own (isMeta): an invoked skill's body when it names a tool use."""
        extra = {"isMeta": True}
        if source_tool_use_id:
            extra["sourceToolUseID"] = source_tool_use_id
        self._row("user", t, {"role": "user", "content": text}, **extra)
        return self

    def attachment(self, t, kind="file", rendered="injected text"):
        """A record Claude Code writes for context it adds on its own (hook output, a file, a reminder)."""
        self.n += 1
        self.rows.append({"type": "attachment", "timestamp": iso(T0 + t), "sessionId": self.sid,
                          "uuid": f"{self.sid}-{self.agent or 'main'}-{self.n}", "attachment": {"type": kind},
                          "rendered": rendered, **({"isSidechain": True, "agentId": self.agent} if self.agent else {})})
        return self

    def compact(self, t):
        self._row("system", t, {}, subtype="compact_boundary")
        return self

    def write(self, root, project="proj"):
        d = os.path.join(root, project)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{self.sid}.jsonl"), "w") as f:
            for r in self.rows:
                f.write(json.dumps(r) + "\n")
        return self
