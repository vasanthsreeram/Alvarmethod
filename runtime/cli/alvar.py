#!/usr/bin/env python3
"""Alvarmethod runtime CLI.

Structured state lives in SQLite; Markdown stays the readable export. The agent
issues commands, this module validates and commits. Standard library only, so a
fresh install needs no package build and no native SQLite driver.

Every command prints one JSON object on stdout. Failures print {"ok": false, "error": ...}
and exit 2, so an agent can branch on the result without parsing prose.

Data directory: --data, else $ALVAR_DATA_DIR, else ./.alvar
Database:      <data>/alvar.db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = RUNTIME_ROOT / "db" / "migrations"
# The newest migration file is the version this runtime expects.
SCHEMA_VERSION = max(int(f.name.split("_", 1)[0]) for f in MIGRATIONS.glob("*.sql"))
DEFAULT_LEARNER = "default"


class AlvarError(Exception):
    """A user-facing, non-crashing failure. Extra keyword fields land in the JSON."""

    def __init__(self, message: str, **fields) -> None:
        super().__init__(message)
        self.fields = fields


def now_dt() -> datetime:
    # $ALVAR_NOW pins the clock, so scheduling is reproducible in tests and replays.
    pinned = os.environ.get("ALVAR_NOW")
    if pinned:
        moment = datetime.fromisoformat(pinned)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).replace(microsecond=0)
    return datetime.now(timezone.utc).replace(microsecond=0)


def now() -> str:
    return now_dt().isoformat()


class Connection(sqlite3.Connection):
    """`with conn:` takes the write lock up front (BEGIN IMMEDIATE).

    A deferred transaction reads, then upgrades to a writer; under concurrent
    writers that upgrade can fail, and read-then-insert steps (next event seq,
    learner row, goal row) can race. Taking the lock first closes both.
    """

    def __enter__(self):
        if not self.in_transaction:
            self.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def open_db(path: Path) -> Connection:
    conn = sqlite3.connect(path, factory=Connection, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def data_dir(args) -> Path:
    raw = getattr(args, "data", None) or os.environ.get("ALVAR_DATA_DIR") or ".alvar"
    return Path(raw).expanduser()


def db_path(args) -> Path:
    return data_dir(args) / "alvar.db"


def connect(args, create: bool = True) -> sqlite3.Connection:
    path = db_path(args)
    if not path.exists():
        if not create:
            raise AlvarError(f"no database at {path}; run 'alvar init' first")
        migrate(args)
    conn = open_db(path)
    conn.execute("PRAGMA journal_mode = WAL")
    version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
    if version is not None and version > SCHEMA_VERSION:
        conn.close()
        raise AlvarError(f"database schema is v{version}, newer than this runtime (v{SCHEMA_VERSION});"
                         " update the skill before using this data directory")
    if version != SCHEMA_VERSION:
        # Older database: migrations are additive, so bring it forward in place.
        conn.close()
        migrate(args)
        conn = open_db(path)
    return conn


def split_sql(script: str) -> list[str]:
    statements, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip() and not all(l.strip().startswith("--") or not l.strip() for l in buf.splitlines()):
        statements.append(buf.strip())
    return statements


def migrate(args) -> dict:
    directory = data_dir(args)
    for sub in ("maps", "sessions", "resources", "visuals", "exports", "backups"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    path = directory / "alvar.db"
    conn = open_db(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        ran = []
        # Each migration and its schema_migrations row commit together, under the
        # write lock, so two processes opening an old database cannot both apply it.
        for sql_file in sorted(MIGRATIONS.glob("*.sql")):
            version = int(sql_file.name.split("_", 1)[0])
            with conn:
                if conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?",
                                (version,)).fetchone():
                    continue
                for statement in split_sql(sql_file.read_text()):
                    if statement.upper().startswith("PRAGMA"):
                        continue
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?,?,?)",
                    (version, sql_file.name, now()),
                )
            ran.append(sql_file.name)
        return {"ok": True, "db": str(path), "applied": ran, "schema_version": SCHEMA_VERSION}
    finally:
        conn.close()


def learner(conn: sqlite3.Connection, slug: str = DEFAULT_LEARNER) -> int:
    row = conn.execute("SELECT id FROM learners WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO learners (slug, display, profile_ref, created_at) VALUES (?,?,?,?)",
        (slug, slug.title(), "LEARNER.md", now()),
    )
    return int(cur.lastrowid)


def slugify(text: str) -> str:
    out = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60] or "goal"


def idempotent(conn: sqlite3.Connection, key: str | None, command: str, run):
    """Retried agent tool calls must not duplicate writes."""
    if key:
        row = conn.execute("SELECT result FROM idempotency WHERE key = ?", (key,)).fetchone()
        if row:
            return {**json.loads(row["result"]), "idempotent_replay": True}
    result = run()
    if key:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO idempotency (key, command, result, created_at) VALUES (?,?,?,?)",
                (key, command, json.dumps(result), now()),
            )
    return result


# ---------------------------------------------------------------- commands

def cmd_init(args) -> dict:
    result = migrate(args)
    conn = connect(args)
    try:
        with conn:
            learner(conn)
        return {**result, "learner": DEFAULT_LEARNER, "ok": True}
    finally:
        conn.close()


def cmd_doctor(args) -> dict:
    checks: dict[str, object] = {"python": sys.version.split()[0], "runtime_root": str(RUNTIME_ROOT)}
    path = db_path(args)
    if not path.exists():
        return {"ok": False, "error": f"no database at {path}", "checks": checks,
                "hint": "run 'alvar init'"}
    conn = connect(args, create=False)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        checks.update({
            "db": str(path),
            "schema_version": version,
            "integrity": integrity,
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
            "tables": len(tables),
        })
        return {"ok": integrity == "ok" and version == SCHEMA_VERSION, "checks": checks}
    finally:
        conn.close()


def cmd_session_create(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                lid = learner(conn, args.learner)
                title = args.goal
                row = conn.execute(
                    "SELECT id FROM goals WHERE learner_id = ? AND slug = ?",
                    (lid, slugify(title)),
                ).fetchone()
                if row:
                    goal_id = row["id"]
                else:
                    goal_id = conn.execute(
                        "INSERT INTO goals (learner_id, title, slug, created_at) VALUES (?,?,?,?)",
                        (lid, title, slugify(title), now()),
                    ).lastrowid
                session_id = int(conn.execute(
                    "INSERT INTO sessions (goal_id, kind, started_at, model) VALUES (?,?,?,?)",
                    (goal_id, args.kind, now(), args.model),
                ).lastrowid)
                event(conn, session_id, "note", detail="session created")
            return {"ok": True, "session_id": session_id, "goal_id": goal_id,
                    "goal": title, "kind": args.kind}
        return idempotent(conn, args.idempotency_key, "session.create", run)
    finally:
        conn.close()


def event(conn: sqlite3.Connection, session_id: int, kind: str, *,
          strand_key=None, node_key=None, outcome=None, detail=None) -> int:
    seq = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM session_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()["s"]
    return int(conn.execute(
        "INSERT INTO session_events (session_id, seq, kind, strand_key, node_key, outcome, detail, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (session_id, seq, kind, strand_key, node_key, outcome, detail, now()),
    ).lastrowid)


def resolve_session(conn: sqlite3.Connection, session_id: int | None) -> sqlite3.Row:
    if session_id is None:
        row = conn.execute(
            "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise AlvarError("no open session; run 'alvar session create --goal ...'")
        return row
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise AlvarError(f"no session {session_id}")
    return row


def cmd_session_resume(args) -> dict:
    conn = connect(args, create=False)
    try:
        row = resolve_session(conn, args.id)
        goal = conn.execute("SELECT * FROM goals WHERE id = ?", (row["goal_id"],)).fetchone()
        events = [dict(r) for r in conn.execute(
            "SELECT seq, kind, strand_key, node_key, outcome FROM session_events"
            " WHERE session_id = ? ORDER BY seq", (row["id"],))]
        progress = plan_progress(conn, row["goal_id"])
        return {"ok": True, "session": dict(row), "goal": dict(goal),
                "events": events, "progress": progress}
    finally:
        conn.close()


def cmd_probe_record(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                session = resolve_session(conn, args.session)
                node = int(conn.execute(
                    "INSERT INTO questions (session_id, strand_key, prompt, options, answer_key, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (session["id"], args.strand, args.question or "(unstated)", None,
                     args.answer or "", now()),
                ).lastrowid)
                event(conn, session["id"], "probe", strand_key=args.strand, outcome=args.status,
                      detail=args.evidence)
            return {"ok": True, "session_id": session["id"], "strand": args.strand,
                    "status": args.status, "question_id": node}
        return idempotent(conn, args.idempotency_key, "probe.record", run)
    finally:
        conn.close()


def cmd_plan_create(args) -> dict:
    payload = json.loads(Path(args.file).read_text()) if args.file else json.load(sys.stdin)
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    conn = connect(args)
    try:
        def run():
            with conn:
                session = resolve_session(conn, args.session)
                goal_id = session["goal_id"]
                conn.execute("DELETE FROM plan_dependencies WHERE goal_id = ?", (goal_id,))
                conn.execute("DELETE FROM plan_nodes WHERE goal_id = ?", (goal_id,))
                for node in nodes:
                    conn.execute(
                        "INSERT INTO plan_nodes (goal_id, node_key, title, claim, grounds, created_at)"
                        " VALUES (?,?,?,?,?,?)",
                        (goal_id, node["id"], node.get("title") or node["id"],
                         node.get("claim"), node.get("grounds"), now()),
                    )
                for edge in edges:
                    conn.execute(
                        "INSERT INTO plan_dependencies (goal_id, from_node, to_node) VALUES (?,?,?)",
                        (goal_id, edge["from"], edge["to"]),
                    )
                event(conn, session["id"], "plan",
                      detail=f"{len(nodes)} nodes, {len(edges)} edges")
                problems = validate_plan(conn, goal_id)
            return {"ok": not problems, "goal_id": goal_id, "nodes": len(nodes),
                    "edges": len(edges), "problems": problems}
        return idempotent(conn, args.idempotency_key, "plan.create", run)
    finally:
        conn.close()


def validate_plan(conn: sqlite3.Connection, goal_id: int) -> list[str]:
    problems: list[str] = []
    keys = {r["node_key"] for r in conn.execute(
        "SELECT node_key FROM plan_nodes WHERE goal_id = ?", (goal_id,))}
    deps = [dict(r) for r in conn.execute(
        "SELECT from_node, to_node FROM plan_dependencies WHERE goal_id = ?", (goal_id,))]
    for dep in deps:
        for side in ("from_node", "to_node"):
            if dep[side] not in keys:
                problems.append(f"edge {dep['from_node']} -> {dep['to_node']}: unknown node {dep[side]}")
    graph: dict[str, list[str]] = {k: [] for k in keys}
    for dep in deps:
        if dep["from_node"] in graph and dep["to_node"] in graph:
            graph[dep["from_node"]].append(dep["to_node"])
    # cycle detection, iterative DFS with colouring
    colour: dict[str, int] = {}

    def visit(start: str) -> bool:
        stack = [(start, iter(graph[start]))]
        colour[start] = 1
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if colour.get(child, 0) == 0:
                    colour[child] = 1
                    stack.append((child, iter(graph.get(child, []))))
                    advanced = True
                    break
                if colour.get(child) == 1:
                    return False
            if not advanced:
                colour[node] = 2
                stack.pop()
        return True

    for key in graph:
        if colour.get(key, 0) == 0 and not visit(key):
            problems.append("plan has a cycle; edges must form a DAG")
            break
    return problems


def plan_progress(conn: sqlite3.Connection, goal_id: int) -> dict:
    nodes = [dict(r) for r in conn.execute(
        "SELECT node_key, title, grounds FROM plan_nodes WHERE goal_id = ? ORDER BY id",
        (goal_id,))]
    order = topological(conn, goal_id)
    tagged = [r["node_key"] for r in conn.execute(
        "SELECT e.node_key FROM session_events e JOIN sessions s ON s.id = e.session_id"
        " WHERE s.goal_id = ? AND e.kind = 'check' AND e.node_key IS NOT NULL ORDER BY e.id",
        (goal_id,))]
    visited: list[str] = []
    for key in tagged:
        if key not in visited:
            visited.append(key)
    current = tagged[-1] if tagged else None
    for node in nodes:
        node["visible_state"] = (
            "current" if node["node_key"] == current
            else "visited" if node["node_key"] in visited
            else "upcoming"
        )
    return {"current": current, "visited": visited, "order": order, "nodes": nodes}


def topological(conn: sqlite3.Connection, goal_id: int) -> list[str]:
    keys = [r["node_key"] for r in conn.execute(
        "SELECT node_key FROM plan_nodes WHERE goal_id = ? ORDER BY id", (goal_id,))]
    deps = [dict(r) for r in conn.execute(
        "SELECT from_node, to_node FROM plan_dependencies WHERE goal_id = ?", (goal_id,))]
    indeg = {k: 0 for k in keys}
    children: dict[str, list[str]] = {k: [] for k in keys}
    for dep in deps:
        if dep["from_node"] in indeg and dep["to_node"] in indeg:
            indeg[dep["to_node"]] += 1
            children[dep["from_node"]].append(dep["to_node"])
    ready = [k for k in keys if indeg[k] == 0]
    out: list[str] = []
    while ready:
        key = ready.pop(0)
        out.append(key)
        for child in children[key]:
            indeg[child] -= 1
            if indeg[child] == 0:
                ready.append(child)
    return out if len(out) == len(keys) else keys


def cmd_plan_validate(args) -> dict:
    conn = connect(args, create=False)
    try:
        goal_id = args.goal or resolve_session(conn, args.session)["goal_id"]
        problems = validate_plan(conn, goal_id)
        return {"ok": not problems, "goal_id": goal_id, "problems": problems}
    finally:
        conn.close()


def cmd_plan_progress(args) -> dict:
    conn = connect(args, create=False)
    try:
        goal_id = args.goal or resolve_session(conn, args.session)["goal_id"]
        return {"ok": True, "goal_id": goal_id, **plan_progress(conn, goal_id)}
    finally:
        conn.close()


def cmd_check_record(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                session = resolve_session(conn, args.session)
                if session["kind"] in ("practice", "review"):
                    raise AlvarError(f"session {session['id']} is a {session['kind']} session;"
                                     " practice and review never move plan position")
                if not args.node:
                    raise AlvarError("a check must carry the node id it is about")
                known = conn.execute(
                    "SELECT 1 FROM plan_nodes WHERE goal_id = ? AND node_key = ?",
                    (session["goal_id"], args.node)).fetchone()
                if not known:
                    raise AlvarError(f"node {args.node} is not on this goal's plan")
                if args.question:
                    # Keep the wording the learner saw, so practice can avoid repeating it.
                    conn.execute(
                        "INSERT INTO questions (session_id, node_key, prompt, answer_key, created_at)"
                        " VALUES (?,?,?,?,?)",
                        (session["id"], args.node, args.question, "", now()),
                    )
                event(conn, session["id"], "check", node_key=args.node,
                      outcome="correct" if args.correct else "incorrect", detail=args.reason)
            return {"ok": True, "session_id": session["id"], "node": args.node,
                    "outcome": "correct" if args.correct else "incorrect"}
        return idempotent(conn, args.idempotency_key, "check.record", run)
    finally:
        conn.close()


def cmd_taught(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                session = resolve_session(conn, args.session)
                event(conn, session["id"], "taught", node_key=args.node, detail=args.detail)
            return {"ok": True, "session_id": session["id"], "node": args.node}
        return idempotent(conn, args.idempotency_key, "taught.record", run)
    finally:
        conn.close()


def cmd_graph_add_proposition(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                lid = learner(conn, args.learner)
                prop_id = int(conn.execute(
                    "INSERT INTO propositions (learner_id, text, status, source_ref, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (lid, args.text, args.status, args.source, now()),
                ).lastrowid)
                if args.source:
                    conn.execute(
                        "INSERT INTO provenance (entity, entity_id, kind, locator, created_at)"
                        " VALUES ('proposition', ?, 'session', ?, ?)",
                        (prop_id, args.source, now()),
                    )
            return {"ok": True, "proposition_id": prop_id, "status": args.status}
        return idempotent(conn, args.idempotency_key, "graph.add_proposition", run)
    finally:
        conn.close()


def cmd_graph_add_chain(args) -> dict:
    premises = [int(p) for p in args.premises.split(",") if p.strip()]
    if not premises:
        raise AlvarError("a reasoning chain needs at least one premise")
    conn = connect(args)
    try:
        def run():
            with conn:
                for pid in premises:
                    if not conn.execute("SELECT 1 FROM propositions WHERE id = ?", (pid,)).fetchone():
                        raise AlvarError(f"premise {pid} is not a proposition")
                if not conn.execute("SELECT 1 FROM propositions WHERE id = ?",
                                    (args.conclusion,)).fetchone():
                    raise AlvarError(f"conclusion {args.conclusion} is not a proposition")
                if args.conclusion in premises:
                    raise AlvarError("a proposition cannot be its own premise")
                chain_id = int(conn.execute(
                    "INSERT INTO reasoning_chains (conclusion_id, note, created_at) VALUES (?,?,?)",
                    (args.conclusion, args.note, now()),
                ).lastrowid)
                for pos, pid in enumerate(premises, start=1):
                    conn.execute(
                        "INSERT INTO chain_premises (chain_id, premise_id, position) VALUES (?,?,?)",
                        (chain_id, pid, pos),
                    )
            return {"ok": True, "chain_id": chain_id, "conclusion": args.conclusion,
                    "premises": premises}
        return idempotent(conn, args.idempotency_key, "graph.add_chain", run)
    finally:
        conn.close()


def cmd_graph_search(args) -> dict:
    conn = connect(args, create=False)
    try:
        like = f"%{args.query}%"
        rows = [dict(r) for r in conn.execute(
            "SELECT id, text, status, source_ref FROM propositions"
            " WHERE text LIKE ? ORDER BY CASE status WHEN 'held' THEN 0 WHEN 'edge' THEN 1 ELSE 2 END, id"
            " LIMIT ?", (like, args.limit))]
        for row in rows:
            row["chains"] = [dict(c) for c in conn.execute(
                "SELECT c.id AS chain_id, p.id AS premise_id, p.text"
                " FROM reasoning_chains c"
                " JOIN chain_premises cp ON cp.chain_id = c.id"
                " JOIN propositions p ON p.id = cp.premise_id"
                " WHERE c.conclusion_id = ? ORDER BY cp.position", (row["id"],))]
        return {"ok": True, "query": args.query, "count": len(rows), "propositions": rows}
    finally:
        conn.close()


def cmd_graph_export(args) -> dict:
    conn = connect(args, create=False)
    try:
        props = [dict(r) for r in conn.execute(
            "SELECT id, text, status, source_ref FROM propositions"
            " ORDER BY CASE status WHEN 'held' THEN 0 WHEN 'edge' THEN 1 ELSE 2 END, id")]
        lines = ["# Graph", "", f"Exported: {now()}", ""]
        for prop in props:
            lines += [f"## Proposition {prop['id']}", prop["text"], ""]
            chains = list(conn.execute(
                "SELECT c.id, p.text FROM reasoning_chains c"
                " JOIN chain_premises cp ON cp.chain_id = c.id"
                " JOIN propositions p ON p.id = cp.premise_id"
                " WHERE c.conclusion_id = ? ORDER BY cp.position", (prop["id"],)))
            if chains:
                lines.append("- chain: " + " -> ".join(row[1] for row in chains))
            lines.append(f"- source: {prop['source_ref'] or 'none'}")
            lines.append(f"- status: {prop['status']}")
            lines.append("")
        text = "\n".join(lines)
        out = Path(args.out) if args.out else data_dir(args) / "exports" / "graph.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        return {"ok": True, "out": str(out), "propositions": len(props), "bytes": len(text)}
    finally:
        conn.close()


def cmd_export(args) -> dict:
    conn = connect(args, create=False)
    try:
        target = Path(args.out) if args.out else data_dir(args) / "exports"
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "exported_at": now(),
            "learners": [dict(r) for r in conn.execute("SELECT id, slug, display FROM learners")],
            "goals": [dict(r) for r in conn.execute("SELECT id, title, status FROM goals")],
            "plan_nodes": [dict(r) for r in conn.execute(
                "SELECT goal_id, node_key, title, grounds FROM plan_nodes ORDER BY id")],
            "plan_dependencies": [dict(r) for r in conn.execute(
                "SELECT goal_id, from_node, to_node FROM plan_dependencies")],
            "session_events": [dict(r) for r in conn.execute(
                "SELECT session_id, seq, kind, strand_key, node_key, outcome, detail"
                " FROM session_events ORDER BY session_id, seq")],
            "propositions": [dict(r) for r in conn.execute(
                "SELECT id, text, status, source_ref FROM propositions ORDER BY id")],
            "chain_premises": [dict(r) for r in conn.execute(
                "SELECT chain_id, premise_id, position FROM chain_premises ORDER BY chain_id, position")],
            "mastery_evidence": [dict(r) for r in conn.execute(
                "SELECT learner_id, proposition_id, node_key, verdict, created_at FROM mastery_evidence")],
        }
        json_path = target / "alvar-export.json"
        json_path.write_text(json.dumps(payload, indent=2))
        graph_path = target / "graph.md"
        cmd_graph_export(argparse.Namespace(**{**vars(args), "out": str(graph_path)}))
        return {"ok": True, "json": str(json_path), "graph": str(graph_path)}
    finally:
        conn.close()


def cmd_backup(args) -> dict:
    directory = data_dir(args)
    path = directory / "alvar.db"
    if not path.exists():
        raise AlvarError(f"no database at {path}")
    backups = directory / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups / f"alvar-{stamp}.db"
    src = sqlite3.connect(path)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return {"ok": True, "backup": str(dest), "bytes": dest.stat().st_size}


def cmd_import_markdown(args) -> dict:
    """Read legacy .alvar/maps/*.md strand tables into the database.

    Handles both shapes the skills have shipped: with an id column and without
    (ids are then assigned s1.. in file order). Re-running records nothing twice.
    """
    import re
    conn = connect(args)
    maps_dir = Path(args.dir) if args.dir else data_dir(args) / "maps"
    if not maps_dir.exists():
        raise AlvarError(f"no maps directory at {maps_dir}")
    report = []
    try:
        for md in sorted(maps_dir.glob("*.md")):
            text = md.read_text()
            goal_match = re.search(r"^Goal:\s*(.+)$", text, re.M)
            heading = re.search(r"^#\s*(?:Map\s*[—-]\s*)?(.+)$", text, re.M)
            title = (goal_match.group(1) if goal_match else heading.group(1) if heading else md.stem).strip()
            goal_slug = slugify(title)
            rows = []
            for line in text.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) < 2:
                    continue
                if set("".join(cells)) <= {"-", ":", " "}:
                    continue
                if cells[0].lower() in ("strand", "id") or cells[1].lower() == "strand":
                    continue
                rows.append(cells)
            if not rows:
                report.append({"file": str(md), "goal": title, "recorded": 0, "note": "no strand rows"})
                continue
            with conn:
                lid = learner(conn, args.learner)
                goal = conn.execute("SELECT id FROM goals WHERE learner_id = ? AND slug = ?",
                                    (lid, goal_slug)).fetchone()
                if goal:
                    goal_id = goal["id"]
                else:
                    goal_id = int(conn.execute(
                        "INSERT INTO goals (learner_id, title, slug, created_at) VALUES (?,?,?,?)",
                        (lid, title, goal_slug, now())).lastrowid)
                seen = {r["strand_key"] for r in conn.execute(
                    "SELECT e.strand_key FROM session_events e JOIN sessions s ON s.id = e.session_id"
                    " WHERE s.goal_id = ? AND e.kind = 'probe'", (goal_id,))}
                session_id = int(conn.execute(
                    "INSERT INTO sessions (goal_id, kind, started_at) VALUES (?,?,?)",
                    (goal_id, "probe", now())).lastrowid)
                recorded = skipped = 0
                for index, cells in enumerate(rows, start=1):
                    if re.fullmatch(r"s\d+", cells[0]):
                        strand_key, rest = cells[0], cells[1:]
                    else:
                        strand_key, rest = f"s{index}", cells
                    if len(rest) >= 3 and rest[1] in ("known", "edge", "unknown", "blocked"):
                        label, status, evidence = rest[0], rest[1], rest[2]
                    elif len(rest) >= 2 and rest[0] in ("known", "edge", "unknown", "blocked"):
                        label, status, evidence = "", rest[0], rest[1]
                    else:
                        skipped += 1
                        continue
                    if strand_key in seen:
                        skipped += 1
                        continue
                    event(conn, session_id, "probe", strand_key=strand_key, outcome=status,
                          detail=(f"{label}: {evidence}" if label else evidence))
                    seen.add(strand_key)
                    recorded += 1
            report.append({"file": str(md), "goal": title, "goal_id": goal_id,
                           "recorded": recorded, "skipped": skipped})
        return {"ok": True, "maps": report}
    finally:
        conn.close()


def cmd_mastery_record(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                lid = learner(conn, args.learner)
                row = int(conn.execute(
                    "INSERT INTO mastery_evidence (learner_id, proposition_id, node_key, verdict, note, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (lid, args.proposition, args.node, args.verdict, args.note, now()),
                ).lastrowid)
            return {"ok": True, "mastery_evidence_id": row, "verdict": args.verdict}
        return idempotent(conn, args.idempotency_key, "mastery.record", run)
    finally:
        conn.close()


# ---------------------------------------------------------------- practice

ITEM_TYPES = ("mcq", "exact", "numeric", "open")
VERDICT_RANK = {"gap": 0, "edge": 1, "held": 2}


def normalize(text: str | None) -> str:
    return " ".join((text or "").casefold().split()).strip(" .?!")


def resolve_goal(conn: sqlite3.Connection, goal_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    if not row:
        raise AlvarError(f"no goal {goal_id}")
    return row


def seen_prompts(conn: sqlite3.Connection, learner_id: int) -> list[str]:
    """Every question wording this learner has already been shown, any session kind."""
    return [r["prompt"] for r in conn.execute(
        "SELECT DISTINCT q.prompt FROM questions q"
        " JOIN sessions s ON s.id = q.session_id JOIN goals g ON g.id = s.goal_id"
        " WHERE g.learner_id = ? AND q.prompt NOT IN ('', '(unstated)') ORDER BY q.id",
        (learner_id,))]


def practice_targets(conn: sqlite3.Connection, learner_id: int, goal_id: int, count: int) -> list[dict]:
    """Held and edge propositions, weakest evidence first, goal-linked first.

    A proposition is linked to the goal when mastery evidence names one of the
    goal's plan nodes, or an earlier question on this goal exercised it.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT id, text, status, source_ref FROM propositions"
        " WHERE (learner_id = ? OR learner_id IS NULL) AND status IN ('held','edge') ORDER BY id",
        (learner_id,))]
    linked = {r["pid"] for r in conn.execute(
        "SELECT me.proposition_id AS pid FROM mastery_evidence me"
        " JOIN plan_nodes n ON n.node_key = me.node_key AND n.goal_id = ?"
        " WHERE me.learner_id = ? AND me.proposition_id IS NOT NULL"
        " UNION SELECT q.proposition_id FROM questions q JOIN sessions s ON s.id = q.session_id"
        " WHERE s.goal_id = ? AND q.proposition_id IS NOT NULL",
        (goal_id, learner_id, goal_id))}
    for row in rows:
        latest = conn.execute(
            "SELECT verdict FROM mastery_evidence WHERE learner_id = ? AND proposition_id = ?"
            " ORDER BY id DESC LIMIT 1", (learner_id, row["id"])).fetchone()
        row["latest_verdict"] = latest["verdict"] if latest else None
        row["practiced"] = conn.execute(
            "SELECT COUNT(*) FROM questions q JOIN sessions s ON s.id = q.session_id"
            " WHERE s.kind = 'practice' AND q.proposition_id = ?", (row["id"],)).fetchone()[0]
        row["goal_linked"] = row["id"] in linked
    # Weakest first: a gap, then edge, then never assessed, then held.
    weakness = {"gap": 0, "edge": 1, None: 2, "held": 3}
    rows.sort(key=lambda r: (not r["goal_linked"], weakness[r["latest_verdict"]], r["practiced"], r["id"]))
    return rows[:count]


def validate_item(item: dict, index: int, allowed: dict[int, dict], avoid: set[str]) -> list[str]:
    where = f"item {index}"
    problems = []
    pid = item.get("proposition_id")
    prompt = (item.get("prompt") or "").strip()
    key = item.get("answer_key")
    item_type = item.get("item_type") or ("mcq" if item.get("options") else "open")
    if pid not in allowed:
        problems.append(f"{where}: proposition {pid} is not a held or edge proposition for this learner")
    if not prompt:
        problems.append(f"{where}: prompt is empty")
    if key is None or str(key).strip() == "":
        problems.append(f"{where}: answer_key must be written before the learner sees the item")
    if item_type not in ITEM_TYPES:
        problems.append(f"{where}: item_type must be one of {', '.join(ITEM_TYPES)}")
    if not (item.get("rubric") or "").strip():
        problems.append(f"{where}: rubric is empty; say what a sound answer must show")
    if prompt and normalize(prompt) in avoid:
        problems.append(f"{where}: prompt repeats wording the learner has already seen; vary the problem")
    if prompt and pid in allowed and normalize(allowed[pid]["text"]) in normalize(prompt):
        problems.append(f"{where}: prompt restates proposition {pid} verbatim; vary the problem, not the fact")
    if item_type == "mcq":
        options = item.get("options") or []
        if len(options) < 2:
            problems.append(f"{where}: an mcq needs at least two options")
        elif key not in options:
            problems.append(f"{where}: an mcq answer_key must be one of its options, verbatim")
    if item_type == "numeric":
        try:
            float(key)
            float(item.get("tolerance") or 0)
        except (TypeError, ValueError):
            problems.append(f"{where}: numeric answer_key and tolerance must be numbers")
    if item.get("distance") not in (None, "familiar", "adjacent", "unfamiliar"):
        problems.append(f"{where}: distance must be familiar, adjacent or unfamiliar")
    return problems


def cmd_practice_create(args) -> dict:
    conn = connect(args)
    try:
        goal = resolve_goal(conn, args.goal)
        lid = goal["learner_id"]
        targets = practice_targets(conn, lid, goal["id"], args.count)
        avoid = seen_prompts(conn, lid)
        if not args.file:
            # Draft mode: what to write items about, and what not to repeat. Writes nothing.
            return {
                "ok": True, "draft": True, "goal_id": goal["id"], "count": args.count,
                "targets": targets, "avoid": avoid,
                "item_shape": {"items": [{
                    "proposition_id": "a target id", "prompt": "a new problem, not the lesson's check",
                    "item_type": "mcq|exact|numeric|open", "options": ["for mcq only"],
                    "answer_key": "written now, immutable", "rubric": "what a sound answer shows",
                    "tolerance": "numeric only", "distance": "familiar|adjacent|unfamiliar"}]},
                "next": "write the items, then run practice-create --goal N --file items.json",
            }
        payload = json.loads(Path(args.file).read_text()) if args.file != "-" else json.load(sys.stdin)
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not items:
            raise AlvarError("no items in the practice file")
        if len(items) > args.count:
            raise AlvarError(f"{len(items)} items exceeds --count {args.count}")
        allowed = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, text, status FROM propositions"
            " WHERE (learner_id = ? OR learner_id IS NULL) AND status IN ('held','edge')", (lid,))}
        avoid_set = {normalize(p) for p in avoid}
        problems: list[str] = []
        for index, item in enumerate(items, start=1):
            problems += validate_item(item, index, allowed, avoid_set)
            avoid_set.add(normalize(item.get("prompt")))
        if problems:
            raise AlvarError("practice items rejected", problems=problems)

        def run():
            with conn:
                session_id = int(conn.execute(
                    "INSERT INTO sessions (goal_id, kind, started_at, model) VALUES (?,?,?,?)",
                    (goal["id"], "practice", now(), args.model)).lastrowid)
                created = []
                for item in items:
                    item_type = item.get("item_type") or ("mcq" if item.get("options") else "open")
                    qid = int(conn.execute(
                        "INSERT INTO questions (session_id, proposition_id, prompt, options, answer_key,"
                        " item_type, rubric, tolerance, distance, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (session_id, item["proposition_id"], item["prompt"].strip(),
                         json.dumps(item["options"]) if item.get("options") else None,
                         str(item["answer_key"]), item_type, item["rubric"],
                         float(item["tolerance"]) if item.get("tolerance") not in (None, "") else None,
                         item.get("distance"), now())).lastrowid)
                    created.append({"question_id": qid, "proposition_id": item["proposition_id"],
                                    "item_type": item_type, "prompt": item["prompt"].strip(),
                                    "options": item.get("options")})
                event(conn, session_id, "note", detail=f"practice set: {len(created)} items")
            return {"ok": True, "session_id": session_id, "goal_id": goal["id"], "kind": "practice",
                    "items": created}
        return idempotent(conn, args.idempotency_key, "practice.create", run)
    finally:
        conn.close()


def auto_grade(question: sqlite3.Row, answer: str) -> bool | None:
    """Grade what can be graded mechanically against the immutable key; None for open items."""
    item_type = question["item_type"]
    key = question["answer_key"]
    if item_type == "mcq":
        options = json.loads(question["options"] or "[]")
        given = answer.strip()
        if len(given) == 1 and given.isalpha() and ord(given.upper()) - 65 < len(options):
            given = options[ord(given.upper()) - 65]
        return normalize(given) == normalize(key)
    if item_type == "exact":
        return normalize(answer) == normalize(key)
    if item_type == "numeric":
        try:
            return abs(float(answer) - float(key)) <= (question["tolerance"] or 0)
        except ValueError:
            return False
    return None


def cmd_practice_submit(args) -> dict:
    conn = connect(args)
    try:
        def run():
            with conn:
                question = conn.execute(
                    "SELECT q.*, s.kind AS session_kind, g.learner_id FROM questions q"
                    " JOIN sessions s ON s.id = q.session_id JOIN goals g ON g.id = s.goal_id"
                    " WHERE q.id = ?", (args.question,)).fetchone()
                if not question:
                    raise AlvarError(f"no question {args.question}")
                if question["session_kind"] != "practice":
                    raise AlvarError(f"question {args.question} is not a practice item")
                if conn.execute("SELECT 1 FROM attempts WHERE question_id = ?", (args.question,)).fetchone():
                    raise AlvarError(f"question {args.question} already has an attempt;"
                                     " write a new item instead of re-asking this one")
                if args.confidence is not None and not 0 <= args.confidence <= 1:
                    raise AlvarError("confidence is a number from 0 to 1")
                judged = True if args.correct else False if args.incorrect else None
                graded = auto_grade(question, args.answer)
                if graded is None:
                    if judged is None:
                        raise AlvarError("open item: grade it against the rubric and pass --correct or --incorrect",
                                         rubric=question["rubric"])
                    correct = judged
                else:
                    if judged is not None and judged != graded:
                        raise AlvarError("the judgment disagrees with the immutable answer key",
                                         key_says="correct" if graded else "incorrect")
                    correct = graded
                reasoned = bool((args.reasoning or "").strip())
                derived = "held" if correct and reasoned else "edge" if correct else "gap"
                verdict = args.verdict or derived
                if verdict == "held" and derived != "held":
                    raise AlvarError("held needs a correct answer with sound reasoning;"
                                     f" this attempt supports at most {derived}")
                raw = json.dumps({"answer": args.answer, "reasoning": args.reasoning,
                                  "confidence": args.confidence})
                attempt_id = int(conn.execute(
                    "INSERT INTO attempts (question_id, learner_id, answer, reasoning, confidence, correct,"
                    " raw, feedback, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (args.question, question["learner_id"], args.answer, args.reasoning, args.confidence,
                     int(correct), raw, args.feedback, now())).lastrowid)
                evidence_id = int(conn.execute(
                    "INSERT INTO mastery_evidence (learner_id, proposition_id, attempt_id, verdict, note,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (question["learner_id"], question["proposition_id"], attempt_id, verdict,
                     f"practice q{args.question}" + (f": {args.feedback}" if args.feedback else ""),
                     now())).lastrowid)
                event(conn, question["session_id"], "note", outcome="correct" if correct else "incorrect",
                      detail=f"practice q{args.question} attempt {attempt_id}, verdict {verdict}")
            return {"ok": True, "question_id": args.question, "attempt_id": attempt_id,
                    "correct": correct, "verdict": verdict, "mastery_evidence_id": evidence_id,
                    "answer_key": question["answer_key"], "rubric": question["rubric"]}
        return idempotent(conn, args.idempotency_key, "practice.submit", run)
    finally:
        conn.close()


def cmd_practice_result(args) -> dict:
    conn = connect(args, create=False)
    try:
        session = resolve_session(conn, args.session)
        if session["kind"] != "practice":
            raise AlvarError(f"session {session['id']} is a {session['kind']} session, not practice")
        items = [dict(r) for r in conn.execute(
            "SELECT q.id AS question_id, q.proposition_id, q.item_type, q.prompt,"
            " a.answer, a.correct, a.confidence, me.verdict"
            " FROM questions q LEFT JOIN attempts a ON a.question_id = q.id"
            " LEFT JOIN mastery_evidence me ON me.attempt_id = a.id"
            " WHERE q.session_id = ? ORDER BY q.id", (session["id"],))]
        answered = [i for i in items if i["correct"] is not None]
        verdicts = {v: sum(1 for i in answered if i["verdict"] == v) for v in ("held", "edge", "gap")}
        return {
            "ok": True, "session_id": session["id"], "goal_id": session["goal_id"],
            "items": items, "total": len(items), "answered": len(answered),
            "correct": sum(1 for i in answered if i["correct"]),
            "unanswered": len(items) - len(answered), "verdicts": verdicts,
            "note": "a practice score is evidence from this set of items, not a mastery grade",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alvar", description="Alvarmethod runtime")
    parser.add_argument("--data", help="learner data directory (default ./.alvar)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        p.add_argument("--idempotency-key", dest="idempotency_key")
        return p

    p = add("init", cmd_init, "create the data directory, database and learner row")
    p.add_argument("--learner", default=DEFAULT_LEARNER)

    add("doctor", cmd_doctor, "check schema version, integrity and pragmas")

    p = add("session-create", cmd_session_create, "start a session against a goal")
    p.add_argument("--goal", required=True)
    p.add_argument("--kind", default="teach", choices=["probe", "teach", "practice", "review"])
    p.add_argument("--model")
    p.add_argument("--learner", default=DEFAULT_LEARNER)

    p = add("session-resume", cmd_session_resume, "state needed to continue a session")
    p.add_argument("--id", type=int)

    p = add("probe-record", cmd_probe_record, "record one strand reading from the probe")
    p.add_argument("--session", type=int)
    p.add_argument("--strand", required=True, help="s1, s2, ...")
    p.add_argument("--status", required=True, choices=["known", "edge", "unknown", "blocked"])
    p.add_argument("--evidence")
    p.add_argument("--question")
    p.add_argument("--answer")

    p = add("plan-create", cmd_plan_create, "write the lesson DAG from JSON (file or stdin)")
    p.add_argument("--session", type=int)
    p.add_argument("--file")

    p = add("plan-validate", cmd_plan_validate, "reject unknown nodes and cycles")
    p.add_argument("--goal", type=int)
    p.add_argument("--session", type=int)

    p = add("plan-progress", cmd_plan_progress, "current and visited nodes, read from events")
    p.add_argument("--goal", type=int)
    p.add_argument("--session", type=int)

    p = add("check-record", cmd_check_record, "record a tagged check on a plan node")
    p.add_argument("--session", type=int)
    p.add_argument("--node", required=True)
    p.add_argument("--correct", action="store_true")
    p.add_argument("--reason")
    p.add_argument("--question", help="the check's wording, kept so practice never repeats it")

    p = add("taught", cmd_taught, "record that a node was taught")
    p.add_argument("--session", type=int)
    p.add_argument("--node", required=True)
    p.add_argument("--detail")

    p = add("graph-add-proposition", cmd_graph_add_proposition, "add one proposition")
    p.add_argument("--text", required=True)
    p.add_argument("--status", default="candidate", choices=["held", "edge", "candidate"])
    p.add_argument("--source", help="sessions/<file>.md#n4")
    p.add_argument("--learner", default=DEFAULT_LEARNER)

    p = add("graph-add-chain", cmd_graph_add_chain, "declare a hyperedge argument")
    p.add_argument("--conclusion", type=int, required=True)
    p.add_argument("--premises", required=True, help="comma separated proposition ids")
    p.add_argument("--note")

    p = add("graph-search", cmd_graph_search, "keyword search over propositions")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=20)

    p = add("graph-export", cmd_graph_export, "write the readable graph export")
    p.add_argument("--out")

    p = add("mastery-record", cmd_mastery_record, "record what the learner showed")
    p.add_argument("--verdict", required=True, choices=["held", "edge", "gap"])
    p.add_argument("--proposition", type=int)
    p.add_argument("--node")
    p.add_argument("--note")
    p.add_argument("--learner", default=DEFAULT_LEARNER)

    p = add("export", cmd_export, "write JSON plus markdown exports")
    p.add_argument("--out")

    p = add("import-markdown", cmd_import_markdown, "read legacy .alvar/maps strand tables into the database")
    p.add_argument("--dir")
    p.add_argument("--learner", default=DEFAULT_LEARNER)

    add("backup", cmd_backup, "consistent copy of the database")

    p = add("practice-create", cmd_practice_create,
            "draft targets for a practice set, or write agent-authored items with --file")
    p.add_argument("--goal", type=int, required=True)
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--file", help="items JSON, or - for stdin; omit to get targets and wordings to avoid")
    p.add_argument("--model")

    p = add("practice-submit", cmd_practice_submit, "grade one practice attempt")
    p.add_argument("--question", type=int, required=True)
    p.add_argument("--answer", required=True)
    p.add_argument("--reasoning")
    p.add_argument("--confidence", type=float, help="0 to 1, as the learner stated it")
    grade = p.add_mutually_exclusive_group()
    grade.add_argument("--correct", action="store_true", help="your judgment on an open item")
    grade.add_argument("--incorrect", action="store_true", help="your judgment on an open item")
    p.add_argument("--verdict", choices=["held", "edge", "gap"], help="override the derived verdict")
    p.add_argument("--feedback")

    p = add("practice-result", cmd_practice_result, "what one practice set showed")
    p.add_argument("--session", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except AlvarError as exc:
        print(json.dumps({"ok": False, "error": str(exc), **exc.fields}))
        return 2
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
