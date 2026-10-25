#!/usr/bin/env python3
"""Runtime tests: schema, plan validation, position-not-completion, graph, recovery.

Run: python3 tests/test_runtime.py
No network, no model, no third-party packages.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "alvar"
PY = sys.executable
MIGRATIONS = ROOT / "runtime" / "db" / "migrations"
LATEST = max(int(f.name.split("_", 1)[0]) for f in MIGRATIONS.glob("*.sql"))


class RuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="alvar-test-"))
        self.env = {**os.environ, "ALVAR_DATA_DIR": str(self.dir), "ALVAR_PYTHON": PY}

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def run_cli(self, *args: str, expect: int = 0, at: str | None = None) -> dict:
        env = {**self.env, "ALVAR_NOW": at} if at else self.env
        proc = subprocess.run(
            ["bash", str(CLI), *args],
            capture_output=True, text=True, env=env, cwd=str(self.dir), check=False,
        )
        self.assertEqual(proc.returncode, expect,
                         f"exit {proc.returncode} for {args}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def write_json(self, name: str, payload) -> str:
        path = self.dir / name
        path.write_text(json.dumps(payload))
        return str(path)

    def query(self, sql: str, params=()) -> list:
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def practice_fixture(self) -> dict:
        """A taught goal: plan, two checks, a held and an edge proposition, one candidate."""
        self.run_cli("init")
        session = self.run_cli("session-create", "--goal", "derivatives")
        self.plan([{"id": "n1", "title": "slope"}, {"id": "n2", "title": "limit"}],
                  [{"from": "n1", "to": "n2"}])
        self.run_cli("check-record", "--node", "n1", "--correct", "--reason", "sound",
                     "--question", "What is the slope of y = 3x + 1?")
        self.run_cli("check-record", "--node", "n2", "--correct", "--reason", "sound")
        held = self.run_cli("graph-add-proposition", "--text", "the slope of a line is rise over run",
                            "--status", "held", "--source", "sessions/d.md#n1")["proposition_id"]
        edge = self.run_cli("graph-add-proposition", "--text", "a derivative is a limit of slopes",
                            "--status", "edge", "--source", "sessions/d.md#n2")["proposition_id"]
        cand = self.run_cli("graph-add-proposition", "--text", "every function has a derivative",
                            "--status", "candidate")["proposition_id"]
        return {"goal": session["goal_id"], "teach_session": session["session_id"],
                "held": held, "edge": edge, "candidate": cand}

    def practice_items(self, f: dict) -> list:
        return [
            {"proposition_id": f["held"], "item_type": "mcq",
             "prompt": "A ramp climbs 2 m over 8 m of floor. What is its slope?",
             "options": ["4", "0.25", "16"], "answer_key": "0.25",
             "rubric": "divides rise by run", "distance": "adjacent"},
            {"proposition_id": f["edge"], "item_type": "open",
             "prompt": "Why does shrinking the gap between two points on a curve give the tangent slope?",
             "answer_key": "the secant slopes approach one value as the gap goes to zero",
             "rubric": "names secant slopes and the limit as the gap shrinks"},
            {"proposition_id": f["edge"], "item_type": "numeric",
             "prompt": "Estimate the slope of y = x^2 at x = 3 using h = 0.001.",
             "answer_key": "6.001", "tolerance": 0.01, "rubric": "computes ((3+h)^2 - 9)/h"},
        ]

    def plan(self, nodes, edges, expect: int = 0) -> dict:
        path = self.dir / "plan.json"
        path.write_text(json.dumps({"nodes": nodes, "edges": edges}))
        return self.run_cli("plan-create", "--file", str(path), expect=expect)

    # -- tests -----------------------------------------------------------
    def test_init_is_idempotent_and_doctor_reports_ok(self) -> None:
        first = self.run_cli("init")
        second = self.run_cli("init")
        self.assertEqual(second["applied"], [], "second init must not re-apply migrations")
        self.assertTrue((self.dir / "alvar.db").exists())
        doctor = self.run_cli("doctor")
        self.assertTrue(doctor["ok"], doctor)
        self.assertEqual(doctor["checks"]["integrity"], "ok")
        self.assertEqual(doctor["checks"]["schema_version"], LATEST)
        self.assertEqual(doctor["checks"]["journal_mode"], "wal")
        self.assertEqual(first["schema_version"], LATEST)

    def test_session_and_probe_are_recorded(self) -> None:
        self.run_cli("init")
        created = self.run_cli("session-create", "--goal", "master immunology", "--kind", "probe")
        self.run_cli("probe-record", "--strand", "s1", "--status", "known", "--evidence", "Q2")
        self.run_cli("probe-record", "--strand", "s2", "--status", "edge")
        resumed = self.run_cli("session-resume", "--id", str(created["session_id"]))
        kinds = [(e["kind"], e["strand_key"], e["outcome"]) for e in resumed["events"]]
        self.assertIn(("probe", "s1", "known"), kinds)
        self.assertIn(("probe", "s2", "edge"), kinds)

    def test_plan_validation_rejects_unknown_nodes_and_cycles(self) -> None:
        self.run_cli("init")
        self.run_cli("session-create", "--goal", "g1")
        bad = self.plan([{"id": "n1", "title": "a"}], [{"from": "n1", "to": "n9"}], expect=1)
        self.assertFalse(bad["ok"])
        self.assertTrue(any("unknown node" in p for p in bad["problems"]), bad)

        cycle = self.plan(
            [{"id": "n1", "title": "a"}, {"id": "n2", "title": "b"}],
            [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n1"}],
            expect=1,
        )
        self.assertFalse(cycle["ok"])
        self.assertTrue(any("cycle" in p for p in cycle["problems"]), cycle)

        good = self.plan(
            [{"id": "n1", "title": "a"}, {"id": "n2", "title": "b", "grounds": "s1"}],
            [{"from": "n1", "to": "n2"}],
        )
        self.assertTrue(good["ok"], good)
        self.assertEqual(self.run_cli("plan-validate")["problems"], [])

    def test_position_not_completion(self) -> None:
        self.run_cli("init")
        self.run_cli("session-create", "--goal", "chain rule")
        self.plan(
            [{"id": "n1", "title": "a"}, {"id": "n2", "title": "b"}, {"id": "n3", "title": "c"}],
            [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        )
        empty = self.run_cli("plan-progress")
        self.assertIsNone(empty["current"], "no fallback current before the first tagged check")
        self.assertEqual(empty["visited"], [])

        self.run_cli("check-record", "--node", "n1", "--correct", "--reason", "sound")
        self.run_cli("check-record", "--node", "n2", "--reason", "said slope of the line")
        progress = self.run_cli("plan-progress")
        self.assertEqual(progress["current"], "n2", "a failed check still moves position")
        self.assertEqual(progress["visited"], ["n1", "n2"], "visited is sticky")
        states = {n["node_key"]: n["visible_state"] for n in progress["nodes"]}
        self.assertEqual(states, {"n1": "visited", "n2": "current", "n3": "upcoming"})

    def test_check_requires_a_real_node(self) -> None:
        self.run_cli("init")
        self.run_cli("session-create", "--goal", "g")
        self.plan([{"id": "n1", "title": "a"}], [])
        missing = self.run_cli("check-record", "--node", "n7", expect=2)
        self.assertFalse(missing["ok"])
        self.assertIn("not on this goal's plan", missing["error"])

    def test_graph_chain_is_a_hyperedge_and_searchable(self) -> None:
        self.run_cli("init")
        a = self.run_cli("graph-add-proposition", "--text", "a limit is a value approached",
                         "--status", "held", "--source", "sessions/s.md#n1")
        b = self.run_cli("graph-add-proposition", "--text", "a difference quotient is an average rate",
                         "--status", "held", "--source", "sessions/s.md#n2")
        c = self.run_cli("graph-add-proposition", "--text",
                         "the derivative is the limit of the difference quotient", "--status", "candidate")
        chain = self.run_cli("graph-add-chain", "--conclusion", str(c["proposition_id"]),
                             "--premises", f"{a['proposition_id']},{b['proposition_id']}")
        self.assertTrue(chain["ok"])
        self.assertEqual(len(chain["premises"]), 2)
        found = self.run_cli("graph-search", "--query", "derivative")
        self.assertEqual(found["count"], 1)
        self.assertEqual(len(found["propositions"][0]["chains"]), 2)
        self_referential = self.run_cli(
            "graph-add-chain", "--conclusion", str(a["proposition_id"]),
            "--premises", str(a["proposition_id"]), expect=2)
        self.assertIn("own premise", self_referential["error"])

    def test_mastery_is_separate_from_knowledge(self) -> None:
        self.run_cli("init")
        prop = self.run_cli("graph-add-proposition", "--text", "the sky is blue", "--status", "held")
        self.run_cli("mastery-record", "--verdict", "gap", "--proposition", str(prop["proposition_id"]),
                     "--note", "said purple")
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            status = conn.execute("SELECT status FROM propositions").fetchone()[0]
            verdict = conn.execute("SELECT verdict FROM mastery_evidence").fetchone()[0]
            props = conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(status, "held", "a learner gap must not demote the proposition")
        self.assertEqual(verdict, "gap")
        self.assertEqual(props, 1, "mastery evidence must not create propositions")

    def test_idempotency_key_replays_without_duplicating(self) -> None:
        self.run_cli("init")
        first = self.run_cli("graph-add-proposition", "--text", "one claim",
                             "--idempotency-key", "abc-1")
        second = self.run_cli("graph-add-proposition", "--text", "one claim",
                              "--idempotency-key", "abc-1")
        self.assertEqual(first["proposition_id"], second["proposition_id"])
        self.assertTrue(second.get("idempotent_replay"))
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0], 1)
        finally:
            conn.close()

    def test_concurrent_writers_keep_integrity(self) -> None:
        self.run_cli("init")
        self.run_cli("session-create", "--goal", "concurrency")
        procs = [
            subprocess.Popen(
                ["bash", str(CLI), "probe-record", "--strand", f"s{i}", "--status", "edge"],
                cwd=str(self.dir), env=self.env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for i in range(1, 9)
        ]
        for proc in procs:
            proc.communicate(timeout=60)
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM session_events WHERE kind='probe'").fetchone()[0], 8)
            seqs = [r[0] for r in conn.execute("SELECT seq FROM session_events ORDER BY seq")]
            self.assertEqual(len(seqs), len(set(seqs)), "event sequence numbers must stay unique")
        finally:
            conn.close()

    def test_uncommitted_write_is_discarded_and_db_stays_sound(self) -> None:
        self.run_cli("init")
        self.run_cli("session-create", "--goal", "crash")
        # Abrupt process death inside an open transaction, the crash window WAL must survive.
        script = (
            "import sqlite3, os, sys\n"
            f"c = sqlite3.connect({str(self.dir / 'alvar.db')!r})\n"
            "c.execute('BEGIN')\n"
            "c.execute(\"INSERT INTO propositions (text, status, created_at) VALUES ('ghost','candidate','now')\")\n"
            "os._exit(9)\n"
        )
        proc = subprocess.run([PY, "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 9)
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM propositions").fetchone()[0], 0)
        finally:
            conn.close()

    def test_import_markdown_is_idempotent(self) -> None:
        self.run_cli("init")
        maps = self.dir / "maps"
        maps.mkdir(exist_ok=True)
        (maps / "synbio.md").write_text(
            "# Map — solid introduction to synthetic biology\n\n"
            "Updated: 2026-08-16\nGoal: Know what synbio is as an engineering practice.\n\n"
            "## Strands\n"
            "| strand | status | evidence |\n"
            "|--------|--------|----------|\n"
            "| what synbio is | edge | Q1 correct, no reason |\n"
            "| DNA assembly | unknown | Q7 Gibson, I don't know |\n\n"
            "## Quiz log\n- Q1 [what synbio is] B, correct\n"
        )
        first = self.run_cli("import-markdown")
        self.assertEqual(first["maps"][0]["recorded"], 2)
        second = self.run_cli("import-markdown")
        self.assertEqual(second["maps"][0]["recorded"], 0, "second import must not duplicate strands")
        self.assertEqual(second["maps"][0]["skipped"], 2)
        conn = sqlite3.connect(self.dir / "alvar.db")
        try:
            rows = conn.execute(
                "SELECT strand_key, outcome FROM session_events WHERE kind='probe' ORDER BY id").fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("s1", "edge"), ("s2", "unknown")])

    def test_export_and_backup(self) -> None:
        self.run_cli("init")
        self.run_cli("graph-add-proposition", "--text", "exported claim", "--status", "held")
        exported = self.run_cli("export")
        payload = json.loads(Path(exported["json"]).read_text())
        self.assertEqual(len(payload["propositions"]), 1)
        self.assertIn("exported claim", Path(exported["graph"]).read_text())
        backup = self.run_cli("backup")
        self.assertTrue(Path(backup["backup"]).exists())
        conn = sqlite3.connect(backup["backup"])
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()

    # -- practice ----------------------------------------------------------
    def test_practice_draft_targets_held_and_edge_and_writes_nothing(self) -> None:
        f = self.practice_fixture()
        self.run_cli("mastery-record", "--verdict", "held", "--proposition", str(f["held"]), "--node", "n1")
        self.run_cli("mastery-record", "--verdict", "edge", "--proposition", str(f["edge"]), "--node", "n2")
        before = self.query("SELECT COUNT(*) FROM sessions")[0][0]
        draft = self.run_cli("practice-create", "--goal", str(f["goal"]), "--count", "5")
        self.assertTrue(draft["draft"])
        self.assertEqual({t["id"] for t in draft["targets"]}, {f["held"], f["edge"]},
                         "candidates are never practice targets")
        self.assertEqual(draft["targets"][0]["id"], f["edge"],
                         "weakest evidence first: edge before held")
        self.assertIn("What is the slope of y = 3x + 1?", draft["avoid"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM sessions")[0][0], before, "a draft writes nothing")

    def test_practice_rejects_repeats_restatements_and_candidates(self) -> None:
        f = self.practice_fixture()
        items = [
            {"proposition_id": f["held"], "prompt": "what is the slope of y = 3x + 1",
             "answer_key": "3", "item_type": "exact", "rubric": "reads the coefficient"},
            {"proposition_id": f["edge"], "prompt": "True or false: a derivative is a limit of slopes.",
             "answer_key": "true", "item_type": "exact", "rubric": "x"},
            {"proposition_id": f["candidate"], "prompt": "Does |x| have a derivative at 0?",
             "answer_key": "no", "item_type": "exact", "rubric": "corner"},
            {"proposition_id": f["held"], "prompt": "Pick one", "options": ["a", "b"],
             "answer_key": "c", "rubric": "r"},
        ]
        bad = self.run_cli("practice-create", "--goal", str(f["goal"]),
                           "--file", self.write_json("bad.json", {"items": items}), expect=2)
        joined = " | ".join(bad["problems"])
        self.assertIn("item 1: prompt repeats wording", joined)
        self.assertIn("item 2: prompt restates proposition", joined)
        self.assertIn("item 3: proposition", joined)
        self.assertIn("item 4: an mcq answer_key must be one of its options", joined)
        self.assertEqual(self.query("SELECT COUNT(*) FROM sessions WHERE kind='practice'")[0][0], 0)

    def test_practice_grades_into_attempts_and_evidence_never_propositions(self) -> None:
        f = self.practice_fixture()
        created = self.run_cli("practice-create", "--goal", str(f["goal"]), "--file",
                               self.write_json("items.json", {"items": self.practice_items(f)}))
        self.assertEqual(created["kind"], "practice")
        q_mcq, q_open, q_num = (i["question_id"] for i in created["items"])
        props_before = self.query("SELECT id, text, status FROM propositions ORDER BY id")
        progress_before = self.run_cli("plan-progress", "--goal", str(f["goal"]))

        mcq = self.run_cli("practice-submit", "--question", str(q_mcq), "--answer", "B",
                           "--reasoning", "2 divided by 8", "--confidence", "0.8")
        self.assertTrue(mcq["correct"])
        self.assertEqual(mcq["verdict"], "held")

        needs_judgment = self.run_cli("practice-submit", "--question", str(q_open),
                                      "--answer", "it gets closer", expect=2)
        self.assertIn("pass --correct or --incorrect", needs_judgment["error"])
        open_item = self.run_cli("practice-submit", "--question", str(q_open),
                                 "--answer", "it gets closer", "--correct")
        self.assertEqual(open_item["verdict"], "edge", "correct without reasoning is edge, not held")

        disagree = self.run_cli("practice-submit", "--question", str(q_num), "--answer", "5",
                                "--correct", expect=2)
        self.assertIn("immutable answer key", disagree["error"])
        wrong = self.run_cli("practice-submit", "--question", str(q_num), "--answer", "5",
                             "--reasoning", "guessed", "--confidence", "0.9")
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["verdict"], "gap")
        again = self.run_cli("practice-submit", "--question", str(q_num), "--answer", "6.001", expect=2)
        self.assertIn("already has an attempt", again["error"])

        attempts = self.query("SELECT answer, reasoning, confidence, correct FROM attempts ORDER BY id")
        self.assertEqual(attempts, [("B", "2 divided by 8", 0.8, 1), ("it gets closer", None, None, 1),
                                    ("5", "guessed", 0.9, 0)])
        evidence = self.query("SELECT proposition_id, verdict FROM mastery_evidence ORDER BY id")
        self.assertEqual(evidence, [(f["held"], "held"), (f["edge"], "edge"), (f["edge"], "gap")])
        self.assertEqual(self.query("SELECT id, text, status FROM propositions ORDER BY id"), props_before,
                         "grading never writes or changes a proposition")
        progress_after = self.run_cli("plan-progress", "--goal", str(f["goal"]))
        self.assertEqual((progress_after["current"], progress_after["visited"]),
                         (progress_before["current"], progress_before["visited"]),
                         "practice must not move plan position")

        result = self.run_cli("practice-result", "--session", str(created["session_id"]))
        self.assertEqual((result["total"], result["answered"], result["correct"]), (3, 3, 2))
        self.assertEqual(result["verdicts"], {"held": 1, "edge": 1, "gap": 1})
        self.assertIn("not a mastery grade", result["note"])

    def test_practice_session_refuses_checks(self) -> None:
        f = self.practice_fixture()
        created = self.run_cli("practice-create", "--goal", str(f["goal"]), "--file",
                               self.write_json("items.json", {"items": self.practice_items(f)[:1]}))
        refused = self.run_cli("check-record", "--session", str(created["session_id"]),
                               "--node", "n1", "--correct", expect=2)
        self.assertIn("never move plan position", refused["error"])
        held_wrong = self.run_cli("practice-submit", "--question", str(created["items"][0]["question_id"]),
                                  "--answer", "4", "--verdict", "held", expect=2)
        self.assertIn("held needs a correct answer", held_wrong["error"])

    # -- review --------------------------------------------------------------
    def test_review_items_come_only_from_failures_and_edge_evidence(self) -> None:
        f = self.practice_fixture()
        day0 = "2026-10-25T09:00:00+00:00"
        created = self.run_cli("practice-create", "--goal", str(f["goal"]), "--file",
                               self.write_json("items.json", {"items": self.practice_items(f)}), at=day0)
        q_mcq, _, q_num = (i["question_id"] for i in created["items"])
        held = self.run_cli("practice-submit", "--question", str(q_mcq), "--answer", "0.25",
                            "--reasoning", "rise over run", at=day0)
        self.assertNotIn("review_item_id", held, "a held attempt schedules nothing")
        wrong = self.run_cli("practice-submit", "--question", str(q_num), "--answer", "9", at=day0)
        self.assertEqual(wrong["review"], "scheduled")
        self.run_cli("mastery-record", "--verdict", "gap", "--proposition", str(f["held"]), at=day0)
        self.assertEqual(self.query("SELECT proposition_id, source_kind FROM review_items"),
                         [(f["edge"], "practice")],
                         "only the practice failure is queued; a teach-time gap and held evidence are not")
        self.run_cli("mastery-record", "--verdict", "edge", "--proposition", str(f["held"]), at=day0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM review_items")[0][0], 2)
        self.assertEqual(self.query("SELECT COUNT(*) FROM review_items WHERE proposition_id = ?",
                                    (f["candidate"],))[0][0], 0, "untouched propositions are never queued")

        now_due = self.run_cli("review-due", at=day0)
        self.assertEqual(now_due["due"], 0, "new items come due a day later, not in the same sitting")
        self.assertEqual(now_due["next_due_at"], "2026-10-26T09:00:00+00:00")
        due = self.run_cli("review-due", at="2026-10-26T09:00:00+00:00")
        self.assertEqual(due["due"], 2)
        first = due["items"][0]
        self.assertEqual(first["proposition_id"], f["edge"])
        self.assertEqual(first["last_evidence"]["answer"], "9")
        self.assertIn("never introduces new material", due["rule"])

    def test_review_schedule_is_deterministic_sm2(self) -> None:
        f = self.practice_fixture()
        t = "2026-10-25T00:00:00+00:00"
        item = self.run_cli("mastery-record", "--verdict", "edge", "--proposition", str(f["edge"]),
                            at=t)["review_item_id"]
        steps = []
        for grade, at in [("good", "2026-10-26T00:00:00+00:00"), ("good", "2026-10-27T00:00:00+00:00"),
                          ("good", "2026-11-02T00:00:00+00:00"), ("hard", "2026-11-17T00:00:00+00:00"),
                          ("again", "2026-12-25T00:00:00+00:00")]:
            r = self.run_cli("review-record", "--item", str(item), "--grade", grade, at=at)
            steps.append((r["reps"], r["interval_days"], r["ease"], r["due_at"]))
        self.assertEqual(steps, [
            (1, 1.0, 2.5, "2026-10-27T00:00:00+00:00"),
            (2, 6.0, 2.5, "2026-11-02T00:00:00+00:00"),
            (3, 15.0, 2.5, "2026-11-17T00:00:00+00:00"),
            (4, 38.0, 2.36, "2026-12-25T00:00:00+00:00"),
            (0, 1.0, 1.56, "2026-12-26T00:00:00+00:00"),
        ])
        self.assertEqual(self.query("SELECT lapses, last_grade FROM review_items WHERE id = ?", (item,)),
                         [(1, "again")])
        self.assertEqual(self.query("SELECT COUNT(*) FROM review_log")[0][0], 5)
        missing = self.run_cli("review-record", "--item", "999", "--grade", "good", expect=2)
        self.assertIn("no review item", missing["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
