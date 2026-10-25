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


class RuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="alvar-test-"))
        self.env = {**os.environ, "ALVAR_DATA_DIR": str(self.dir), "ALVAR_PYTHON": PY}

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # -- helpers ---------------------------------------------------------
    def run_cli(self, *args: str, expect: int = 0) -> dict:
        proc = subprocess.run(
            ["bash", str(CLI), *args],
            capture_output=True, text=True, env=self.env, cwd=str(self.dir), check=False,
        )
        self.assertEqual(proc.returncode, expect,
                         f"exit {proc.returncode} for {args}\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

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
        self.assertEqual(doctor["checks"]["schema_version"], 1)
        self.assertEqual(doctor["checks"]["journal_mode"], "wal")
        self.assertEqual(first["schema_version"], 1)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
