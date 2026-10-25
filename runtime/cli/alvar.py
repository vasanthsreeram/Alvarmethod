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
SCHEMA_VERSION = 1
DEFAULT_LEARNER = "default"


class AlvarError(Exception):
    """A user-facing, non-crashing failure."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()["v"]
    if version != SCHEMA_VERSION:
        conn.close()
        raise AlvarError(f"database schema is v{version}, runtime expects v{SCHEMA_VERSION}; run 'alvar doctor'")
    return conn


def migrate(args) -> dict:
    directory = data_dir(args)
    for sub in ("maps", "sessions", "resources", "visuals", "exports", "backups"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    path = directory / "alvar.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        ran = []
        for sql_file in sorted(MIGRATIONS.glob("*.sql")):
            version = int(sql_file.name.split("_", 1)[0])
            if version in applied:
                continue
            conn.executescript(sql_file.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?,?,?)",
                (version, sql_file.name, now()),
            )
            ran.append(sql_file.name)
        conn.commit()
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
                if not args.node:
                    raise AlvarError("a check must carry the node id it is about")
                known = conn.execute(
                    "SELECT 1 FROM plan_nodes WHERE goal_id = ? AND node_key = ?",
                    (session["goal_id"], args.node)).fetchone()
                if not known:
                    raise AlvarError(f"node {args.node} is not on this goal's plan")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except AlvarError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    except (sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
