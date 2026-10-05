"""Tests for the leak report's sizing, row isolation and cost invariants.

Every test builds its own transcripts under a temp directory and never reads ~/.claude. Each assertion
states the arithmetic or the property it guards; a test that would pass on wrong code is a defect.
Run: python3 -m unittest discover -s plugins/token-metrics/tests -v
"""
import contextlib
import io
import math
import os
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import leak_categories  # noqa: E402
import leak_extra  # noqa: E402
import leak_report as lr  # noqa: E402
from transcripts import Transcript  # noqa: E402

BIG = "x" * 4000          # a tool result of 4,000 characters


def analyse_root(root):
    """Everything main() does, without argparse: findings for every session under root."""
    findings = defaultdict(list)
    sessions = lr.load_sessions(root, 0)
    for sid, entries in sessions.items():
        lr.analyse(lr.Session(sid, entries, 2.0, 3600, {}, sessions.before.get(sid)), findings)
    lr.cross_session(findings)
    return findings


def one_tool_session(sid, result_tokens, text=BIG, project_text="do the thing"):
    """Two calls and one clean result between them: ctx(call 2) = ctx(call 1) + out(call 1) + result tokens."""
    return (Transcript(sid).prompt(0, project_text)
            .call(1, ctx=60_000, out=100, tools=[(f"{sid}-t1", "Read", {"file_path": "/a"})])
            .result(2, f"{sid}-t1", text)
            .call(3, ctx=60_000 + 100 + result_tokens, out=50))


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        lr.set_units("usd")

    def tearDown(self):
        lr.set_units("usd")      # UNITS is module-global; a leaked "tokens" would corrupt every later test
        self._tmp.cleanup()

    def session(self, tr, project="proj"):
        tr.write(self.root, project)
        sessions = lr.load_sessions(self.root, 0)
        return lr.Session(tr.sid, sessions[tr.sid], 2.0, 3600, {})


class ExactSizing(Base):
    def test_clean_gap_gives_the_exact_context_growth(self):
        s = self.session(one_tool_session("a", 1234))
        r = s.results[0]
        self.assertTrue(r["exact"])
        self.assertEqual(r["tokens"], 1234)          # not chars/2.37 = 1687

    def test_estimate_is_used_and_flagged_when_a_prompt_intervenes(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .prompt(2.5, "another question")
              .call(3, 60_000 + 100 + 1234 + 40, 50))
        r = self.session(tr).results[0]
        self.assertFalse(r["exact"])
        self.assertEqual(r["tokens"], int(4000 / lr.CHARS_PER_TOKEN["new"]))

    def test_compaction_between_calls_disables_exactness(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .compact(2.5)
              .call(3, 60_000 + 100 + 1234, 50))
        self.assertFalse(self.session(tr).results[0]["exact"])

    def test_parallel_tool_calls_are_not_attributed_to_one_result(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {}), ("t2", "Read", {})])
              .result(2, "t1", BIG).result(2, "t2", BIG)
              .call(3, 60_000 + 100 + 2468, 50))
        s = self.session(tr)
        self.assertEqual([r["exact"] for r in s.results], [False, False])

    def test_skill_body_loaded_in_the_gap_disables_exactness(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Skill", {"skill": "x"})]).result(2, "t1", "Launching skill")
              .meta(2.2, "s" * 8000, source_tool_use_id="t1")
              .call(3, 60_000 + 100 + 3000, 50))
        r = self.session(tr).results[0]
        self.assertFalse(r["exact"])       # the growth is the result plus the skill body, not the result

    def test_injected_meta_message_in_the_gap_disables_exactness(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .meta(2.2)
              .call(3, 60_000 + 100 + 1234, 50))
        self.assertFalse(self.session(tr).results[0]["exact"])

    def test_model_switch_between_calls_disables_exactness(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .call(3, 60_000 + 100 + 1234, 50, model="claude-sonnet-4-6"))
        self.assertFalse(self.session(tr).results[0]["exact"])

    def test_non_positive_growth_is_not_used(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .call(3, 60_000, 50))                  # context did not grow: cannot be a measurement
        r = self.session(tr).results[0]
        self.assertFalse(r["exact"])
        self.assertGreater(r["tokens"], 0)

    def test_small_results_are_sized_exactly_too(self):
        s = self.session(one_tool_session("a", 37, text="ok"))
        self.assertEqual((s.results[0]["exact"], s.results[0]["tokens"]), (True, 37))

    def test_exact_size_does_not_depend_on_units(self):
        lr.set_units("tokens")
        s = self.session(one_tool_session("a", 1234))
        self.assertEqual(s.results[0]["tokens"], 1234)

    def test_calibration_still_ignores_small_results(self):
        # 10 clean small results must not produce a per-session chars/token ratio (they are mostly overhead)
        tr = Transcript("a").prompt(0)
        ctx = 60_000
        for n in range(12):
            tr.call(1 + 2 * n, ctx, 10, tools=[(f"t{n}", "Read", {})]).result(2 + 2 * n, f"t{n}", "ok")
            ctx += 10 + 15
        tr.call(30, ctx, 10)
        s = self.session(tr)
        self.assertEqual(s.calibration, {})


class Report(Base):
    def test_report_prints_exact_over_total_sizes(self):
        tr = (Transcript("a").prompt(0)
              .call(1, 60_000, 100, tools=[("t1", "Read", {})]).result(2, "t1", BIG)
              .call(3, 60_000 + 100 + 1234, 100, tools=[("t2", "Read", {})]).result(4, "t2", BIG)
              .prompt(4.5, "interrupt the gap")
              .call(5, 60_000 + 200 + 2500, 50))
        tr.write(self.root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            lr.report(analyse_root(self.root))
        self.assertIn("1 of 2 tool-result sizes (50%) are exact", buf.getvalue())

    def test_cli_runs_end_to_end_and_exits_zero(self):
        one_tool_session("a", 1234).write(self.root)
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "leak_report.py"), "--root", self.root,
                            "--events", os.path.join(self.root, "none.jsonl")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("1 of 1 tool-result sizes", p.stdout)
        self.assertIn("each tool result counted once", p.stdout)


class RowIsolation(Base):
    """Analysing a session must not depend on which other sessions are in the run, or their order."""

    @staticmethod
    def by_session(findings, sid8):
        return {k: sorted((round(i["cost"], 9), i["detail"]) for i in v if i["session"] == sid8)
                for k, v in findings.items() if not str(k).startswith("_")
                and any(i["session"] == sid8 for i in v)}

    def make(self, sid, text):
        one_tool_session(sid, 1234, project_text=text).write(self.root, "p-" + sid)

    def test_a_session_costs_the_same_alone_and_with_an_unrelated_neighbour(self):
        self.make("aaaaaaaa1", "fix the parser")
        alone = self.by_session(analyse_root(self.root), "aaaaaaaa")
        self.assertTrue(alone, "no finding fired for the session: the comparison would measure nothing")
        self.make("bbbbbbbb1", "write the release notes")
        both = self.by_session(analyse_root(self.root), "aaaaaaaa")
        self.assertEqual(alone, both)

    def test_neighbour_sessions_are_charged_their_own_findings(self):
        self.make("aaaaaaaa1", "fix the parser")
        self.make("bbbbbbbb1", "write the release notes")
        f = analyse_root(self.root)
        self.assertEqual(self.by_session(f, "aaaaaaaa").keys(), self.by_session(f, "bbbbbbbb").keys())
        self.assertTrue(self.by_session(f, "bbbbbbbb"))

    def test_analysis_order_does_not_change_a_sessions_findings(self):
        self.make("aaaaaaaa1", "fix the parser")
        self.make("bbbbbbbb1", "write the release notes")
        sessions = lr.load_sessions(self.root, 0)
        results = []
        for order in (sorted(sessions), sorted(sessions, reverse=True)):
            f = defaultdict(list)
            for sid in order:
                lr.analyse(lr.Session(sid, sessions[sid], 2.0, 3600, {}), f)
            lr.cross_session(f)
            results.append((self.by_session(f, "aaaaaaaa"), self.by_session(f, "bbbbbbbb")))
        self.assertEqual(results[0], results[1])

    def test_one_leak_does_not_change_another_leaks_cost(self):
        # Add a big result (feeds result-carrying leaks) to a copy of the session; the starting-context
        # leak (#1) depends only on the first call and must not move.
        self.make("aaaaaaaa1", "fix the parser")
        base = self.by_session(analyse_root(self.root), "aaaaaaaa")[1]
        (Transcript("aaaaaaaa1").prompt(0, "fix the parser")
         .call(1, ctx=60_000, out=100, tools=[("t1", "Read", {"file_path": "/a"})])
         .result(2, "t1", "y" * 200_000)
         .call(3, ctx=60_000 + 100 + 80_000, out=50)).write(self.root, "p-aaaaaaaa1")
        changed = self.by_session(analyse_root(self.root), "aaaaaaaa")
        self.assertEqual(base, changed[1])
        self.assertNotEqual(changed.keys() - {1}, set(), "the large result should have triggered other leaks")


class ResumedSession(Base):
    """Resuming or forking a session copies its history, same uuids, into a second transcript file."""

    def test_a_history_copied_into_a_second_file_is_counted_once(self):
        tr = one_tool_session("aaaaaaaa1", 1234)
        tr.write(self.root, "original")
        once = analyse_root(self.root)
        self.assertTrue(once["_sessions"], "no session analysed: the comparison would measure nothing")
        tr.write(os.path.join(self.root, "resumed"), "copy")
        twice = analyse_root(self.root)
        self.assertEqual(len(lr.load_sessions(self.root, 0)["aaaaaaaa1"]), len(tr.rows))
        total = lambda f: sum(i["cost"] for k, v in f.items() if not str(k).startswith("_") for i in v)
        self.assertGreater(total(once), 0)
        self.assertAlmostEqual(total(once), total(twice))
        self.assertEqual(lr.reconcile(twice), [])

    def test_distinct_entries_that_share_no_uuid_are_all_kept(self):
        one_tool_session("aaaaaaaa1", 1234).write(self.root, "p")
        n = len(lr.load_sessions(self.root, 0)["aaaaaaaa1"])
        self.assertEqual(n, 4)


class Reconcile(Base):
    def findings(self):
        one_tool_session("aaaaaaaa1", 1234).write(self.root)
        return analyse_root(self.root)

    def test_clean_run_reconciles_and_checked_something(self):
        f = self.findings()
        self.assertGreater(sum(len(v) for k, v in f.items() if not str(k).startswith("_")), 0)
        self.assertEqual(lr.reconcile(f), [])

    def test_cost_above_the_sessions_spend_is_reported(self):
        f = self.findings()
        s = f["_sessions"][0]
        f[1].append({"cost": (s.cost + s.helper_cost) * 2, "session": s.sid[:8], "project": "p",
                     "detail": "x", "ref": None, "overlap": False})
        self.assertTrue(any("charged" in m and "spent" in m for m in lr.reconcile(f)))

    def test_per_session_total_not_just_single_items_is_bounded(self):
        f = self.findings()
        s = f["_sessions"][0]
        half = (s.cost + s.helper_cost) * 0.6
        for _ in range(2):
            f[2].append({"cost": half, "session": s.sid[:8], "project": "p", "detail": "x", "ref": None,
                         "overlap": False})
        self.assertTrue(any("leak 2" in m for m in lr.reconcile(f)))

    def test_negative_nan_and_infinite_costs_are_reported(self):
        for bad in (-1.0, math.nan, math.inf):
            f = self.findings()
            f[3].append({"cost": bad, "session": f["_sessions"][0].sid[:8], "project": "p", "detail": "x",
                         "ref": None, "overlap": False})
            self.assertTrue(any("has cost" in m for m in lr.reconcile(f)), bad)

    def test_finding_for_an_unknown_session_is_reported(self):
        f = self.findings()
        f[3].append({"cost": 0.0, "session": "ghost000", "project": "p", "detail": "x", "ref": None,
                     "overlap": False})
        self.assertTrue(any("ghost000" in m for m in lr.reconcile(f)))

    def test_category_reading_an_unknown_finding_key_is_reported(self):
        f = self.findings()
        cats = dict(leak_categories.CATEGORIES)
        name, group, sources = cats[1]
        cats[1] = (name, group, [*sources, 99_999])
        with mock.patch.dict(leak_categories.CATEGORIES, cats):
            self.assertTrue(any("99999" in m for m in lr.reconcile(f)))


class DistinctFlagged(unittest.TestCase):
    @staticmethod
    def rows(*item_lists):
        return [(n, f"row {n}", "g", sum(i["cost"] for i in items), items, None, "")
                for n, items in enumerate(item_lists, 1)]

    @staticmethod
    def item(ref, cost, session="aaaaaaaa"):
        return {"cost": cost, "session": session, "project": "p", "detail": "", "ref": ref, "overlap": False}

    def findings(self, spent):
        return {"_sessions": [SimpleNamespace(sid="aaaaaaaa-1", cost=spent, helper_cost=0.0)]}

    def test_a_result_flagged_by_two_rows_counts_once_at_its_largest_charge(self):
        rows = self.rows([self.item("aaaaaaaa-1:t1", 5.0)], [self.item("aaaaaaaa-1:t1", 3.0)])
        self.assertEqual(lr.distinct_flagged(self.findings(100.0), rows), 5.0)

    def test_different_results_add_up(self):
        rows = self.rows([self.item("aaaaaaaa-1:t1", 5.0)], [self.item("aaaaaaaa-1:t2", 3.0)])
        self.assertEqual(lr.distinct_flagged(self.findings(100.0), rows), 8.0)

    def test_session_is_capped_at_what_it_spent(self):
        rows = self.rows([self.item("aaaaaaaa-1:t1", 80.0)], [self.item(None, 80.0)])
        self.assertEqual(lr.distinct_flagged(self.findings(100.0), rows), 100.0)

    def test_unmeasurable_rows_are_ignored(self):
        rows = [(1, "r", "g", 0.0, [self.item("aaaaaaaa-1:t1", 9.0)], "no data", "")]
        self.assertEqual(lr.distinct_flagged(self.findings(100.0), rows), 0.0)


class Partition(unittest.TestCase):
    def test_there_are_50_curated_rows_numbered_1_to_50(self):
        self.assertEqual(sorted(leak_categories.CATEGORIES), list(range(1, 51)))

    def test_additional_row_keys_cannot_collide_with_core_ids(self):
        core = set(lr.LEAKS)
        self.assertTrue(all(lr.lid(n) not in core for n in leak_extra.ADDITIONAL))
        self.assertEqual(len({lr.lid(n) for n in leak_extra.ADDITIONAL}), len(leak_extra.ADDITIONAL))

    def test_every_curated_source_is_a_real_detector(self):
        known = set(lr.LEAKS) | set(lr.PARENT) | {lr.lid(n) for n in leak_extra.ADDITIONAL}
        for n, (_, _, sources) in leak_categories.CATEGORIES.items():
            self.assertTrue(sources, f"category {n} sums nothing")
            self.assertLessEqual(set(sources), known, f"category {n}")

    def test_aliases_point_at_existing_core_leaks_and_not_at_themselves(self):
        for a, core in leak_extra.SAME_AS.items():
            self.assertIn(a, leak_extra.ADDITIONAL)
            self.assertIn(core, lr.LEAKS)

    def test_full_list_is_135_rows(self):
        self.assertEqual(len(lr.LEAKS) + len(leak_extra.ADDITIONAL), 135)


class Merge(unittest.TestCase):
    def test_same_result_flagged_by_two_sources_of_one_row_counts_once(self):
        f = {1: [{"cost": 5.0, "ref": "s:t", "overlap": False}], 2: [{"cost": 3.0, "ref": "s:t", "overlap": False}]}
        self.assertEqual(sum(i["cost"] for i in lr.merged_items([1, 2], f)), 5.0)

    def test_same_tool_id_in_two_sessions_is_not_merged(self):
        s1, s2 = SimpleNamespace(sid="s1", project="p"), SimpleNamespace(sid="s2", project="p")
        f = defaultdict(list)
        lr.add_finding(f, 1, s1, 5.0, "d", ref="toolu_1")
        lr.add_finding(f, 2, s2, 3.0, "d", ref="toolu_1")     # a forked session replays the same tool id
        self.assertEqual(sum(i["cost"] for i in lr.merged_items([1, 2], f)), 8.0)

    def test_overlap_findings_stay_out_of_curated_rows(self):
        f = {1: [{"cost": 5.0, "ref": None, "overlap": True}]}
        self.assertEqual(lr.merged_items([1], f), [])


if __name__ == "__main__":
    unittest.main()
