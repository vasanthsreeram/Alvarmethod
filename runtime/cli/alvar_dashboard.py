"""Read-only local dashboard for the Alvarmethod runtime.

Renders one self-contained HTML page (inline CSS, hand-drawn SVG, no script, no
CDN) from the SQLite database, and serves it on 127.0.0.1. Every request re-reads
the database, so the page shows the same state the agent reads and writes.
The database is opened read-only; this module never writes.
"""
from __future__ import annotations

import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

NODE_W, NODE_H, COL_GAP, ROW_GAP, PAD = 168, 46, 64, 22, 20

CSS = """
:root { --ink:#1d2330; --muted:#6b7385; --line:#d5d9e2; --bg:#f7f8fb; --card:#fff;
        --accent:#2f5bd3; --accent-soft:#e3eafc; --held:#2e7d4f; --edge:#b7791f; --cand:#7a8194; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; color:var(--ink); background:var(--bg); }
header { padding:20px 28px 8px; }
header h1 { margin:0; font-size:20px; }
header p { margin:4px 0 0; color:var(--muted); font-size:13px; }
nav { padding:0 28px 8px; font-size:13px; }
nav a { color:var(--accent); margin-right:14px; text-decoration:none; }
nav a.on { font-weight:600; text-decoration:underline; }
main { display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:16px; padding:8px 28px 28px; }
section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }
section.wide { grid-column:1 / -1; }
h2 { margin:0 0 10px; font-size:15px; }
.muted { color:var(--muted); font-size:13px; }
.empty { color:var(--muted); font-style:italic; }
.stat { font-size:30px; font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:500; }
ul { margin:0; padding-left:18px; }
li { margin:3px 0; }
.tag { display:inline-block; font-size:11px; padding:1px 7px; border-radius:9px; color:#fff; margin-left:4px; }
.t-held { background:var(--held); } .t-edge { background:var(--edge); } .t-candidate { background:var(--cand); }
.t-gap { background:#b23b3b; }
.legend span { margin-right:14px; font-size:12px; color:var(--muted); }
.legend i { display:inline-block; width:14px; height:10px; border-radius:3px; margin-right:4px; vertical-align:middle; }
svg text { font:12px -apple-system, "Segoe UI", Roboto, sans-serif; }
.n-current rect { fill:var(--accent); stroke:var(--accent); stroke-width:2.5; }
.n-current text { fill:#fff; font-weight:600; }
.n-visited rect { fill:var(--accent-soft); stroke:var(--accent); stroke-width:1.5; }
.n-visited text { fill:var(--ink); }
.n-upcoming rect { fill:#fff; stroke:var(--line); stroke-dasharray:4 3; }
.n-upcoming text { fill:var(--muted); }
.n-upcoming { opacity:.6; }
.edge-line { stroke:#9aa2b4; stroke-width:1.3; fill:none; }
.scroll { overflow-x:auto; }
.empty-state { max-width:560px; margin:60px auto; text-align:center; }
.empty-state code { background:#eef0f5; padding:2px 6px; border-radius:4px; }
"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"
    )


def empty_state(reason: str, db: Path) -> str:
    return page("Alvar dashboard", (
        "<div class=\"empty-state\"><h1>Nothing recorded yet</h1>"
        f"<p>{esc(reason)}</p>"
        "<p class=\"muted\">Start a lesson with <code>/teach</code>, or run "
        "<code>alvar init</code> in your learning folder. This page fills in as the agent records "
        "probes, plans, checks, practice and reviews.</p>"
        f"<p class=\"muted\">Database: {esc(db)} · read-only</p></div>"
    ))


def open_ro(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def layout(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """Layered layout: column = longest prerequisite path, row = order within the column."""
    parents: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in edges:
        if a in parents and b in parents:
            parents[b].append(a)
    depth: dict[str, int] = {}

    def depth_of(node: str, trail: frozenset = frozenset()) -> int:
        if node in depth:
            return depth[node]
        if node in trail:  # a cycle should never reach here; plan-create rejects it
            return 0
        d = 0 if not parents[node] else 1 + max(depth_of(p, trail | {node}) for p in parents[node])
        depth[node] = d
        return d

    rows: dict[int, int] = {}
    pos = {}
    for node in nodes:
        col = depth_of(node)
        pos[node] = (col, rows.get(col, 0))
        rows[col] = rows.get(col, 0) + 1
    return pos


def dag_svg(nodes: list[dict], edges: list[tuple[str, str]]) -> str:
    keys = [n["node_key"] for n in nodes]
    pos = layout(keys, edges)
    cols = max((c for c, _ in pos.values()), default=0) + 1
    rows = max((r for _, r in pos.values()), default=0) + 1
    width = PAD * 2 + cols * NODE_W + (cols - 1) * COL_GAP
    height = PAD * 2 + rows * NODE_H + (rows - 1) * ROW_GAP

    def xy(key: str) -> tuple[int, int]:
        c, r = pos[key]
        return PAD + c * (NODE_W + COL_GAP), PAD + r * (NODE_H + ROW_GAP)

    parts = [f"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{width}\" height=\"{height}\""
             f" viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"lesson plan\">",
             "<defs><marker id=\"arrow\" viewBox=\"0 0 10 10\" refX=\"9\" refY=\"5\" markerWidth=\"7\""
             " markerHeight=\"7\" orient=\"auto-start-reverse\"><path d=\"M0,0 L10,5 L0,10 z\""
             " fill=\"#9aa2b4\"/></marker></defs>"]
    for a, b in edges:
        if a not in pos or b not in pos:
            continue
        ax, ay = xy(a)
        bx, by = xy(b)
        x1, y1 = ax + NODE_W, ay + NODE_H // 2
        x2, y2 = bx, by + NODE_H // 2
        mid = (x1 + x2) / 2
        parts.append(f"<path class=\"edge-line\" marker-end=\"url(#arrow)\""
                     f" d=\"M{x1},{y1} C{mid},{y1} {mid},{y2} {x2 - 2},{y2}\"/>")
    for node in nodes:
        x, y = xy(node["node_key"])
        label = f"{node['node_key']} · {node['title']}"
        short = label if len(label) <= 24 else label[:23] + "…"
        parts.append(
            f"<g class=\"n-{esc(node['visible_state'])}\"><title>{esc(label)}</title>"
            f"<rect x=\"{x}\" y=\"{y}\" width=\"{NODE_W}\" height=\"{NODE_H}\" rx=\"8\"/>"
            f"<text x=\"{x + 10}\" y=\"{y + NODE_H // 2 + 4}\">{esc(short)}</text></g>")
    parts.append("</svg>")
    return "".join(parts)


def progress(conn: sqlite3.Connection, goal_id: int) -> dict:
    nodes = [dict(r) for r in conn.execute(
        "SELECT node_key, title FROM plan_nodes WHERE goal_id = ? ORDER BY id", (goal_id,))]
    edges = [(r["from_node"], r["to_node"]) for r in conn.execute(
        "SELECT from_node, to_node FROM plan_dependencies WHERE goal_id = ? ORDER BY id", (goal_id,))]
    tagged = [r["node_key"] for r in conn.execute(
        "SELECT e.node_key FROM session_events e JOIN sessions s ON s.id = e.session_id"
        " WHERE s.goal_id = ? AND e.kind = 'check' AND e.node_key IS NOT NULL ORDER BY e.id", (goal_id,))]
    current = tagged[-1] if tagged else None
    visited = list(dict.fromkeys(tagged))
    for node in nodes:
        node["visible_state"] = ("current" if node["node_key"] == current
                                 else "visited" if node["node_key"] in visited else "upcoming")
    return {"nodes": nodes, "edges": edges, "current": current, "visited": visited}


def render(db: Path, goal_id: int | None, expected_version: int, now: str) -> str:
    if not db.exists():
        return empty_state("There is no database in this data directory yet.", db)
    conn = open_ro(db)
    try:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        if version != expected_version:
            return empty_state(
                f"This database is schema v{version}; this dashboard reads v{expected_version}. "
                "Run 'alvar doctor' once to migrate it, then reload.", db)
        goals = [dict(r) for r in conn.execute(
            "SELECT g.id, g.title, MAX(s.started_at) AS last FROM goals g"
            " LEFT JOIN sessions s ON s.goal_id = g.id GROUP BY g.id ORDER BY last DESC, g.id DESC")]
        props = [dict(r) for r in conn.execute(
            "SELECT id, text, status, source_ref FROM propositions ORDER BY id")]
        resources = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]
        if not goals and not props and not resources:
            return empty_state("The database exists but holds no goals, propositions or documents yet.", db)
        goal = next((g for g in goals if g["id"] == goal_id), goals[0] if goals else None)
        body = [f"<header><h1>{esc(goal['title']) if goal else 'Knowledge graph'}</h1>"
                f"<p>Read-only view of {esc(db)} · rendered {esc(now)} · reload to refresh</p></header>"]
        if len(goals) > 1:
            links = []
            for g in goals:
                on = ' class="on"' if goal and g["id"] == goal["id"] else ""
                links.append(f"<a href=\"?goal={g['id']}\"{on}>{esc(g['title'])}</a>")
            body.append("<nav>" + "".join(links) + "</nav>")
        body.append("<main>")
        body.append(plan_section(conn, goal))
        body.append(review_section(conn, now))
        body.append(practice_section(conn, goal))
        body.append(propositions_section(props))
        body.append(resources_section(conn))
        body.append("</main>")
        return page(f"Alvar · {goal['title'] if goal else 'graph'}", "".join(body))
    finally:
        conn.close()


def plan_section(conn, goal) -> str:
    out = ["<section class=\"wide\"><h2>Lesson plan</h2>"]
    if not goal:
        return out[0] + "<p class=\"empty\">No goal yet.</p></section>"
    state = progress(conn, goal["id"])
    if not state["nodes"]:
        out.append("<p class=\"empty\">No plan recorded for this goal yet.</p></section>")
        return "".join(out)
    out.append("<p class=\"legend\"><span><i style=\"background:#2f5bd3\"></i>current</span>"
               "<span><i style=\"background:#e3eafc;border:1px solid #2f5bd3\"></i>visited</span>"
               "<span><i style=\"background:#fff;border:1px dashed #d5d9e2\"></i>upcoming</span></p>")
    out.append(f"<div class=\"scroll\">{dag_svg(state['nodes'], state['edges'])}</div>")
    current = state["current"] or "none yet (no tagged check)"
    out.append(f"<p class=\"muted\">Current: <b>{esc(current)}</b> · visited: "
               f"{esc(', '.join(state['visited']) or 'none')}. Position comes from the most recent "
               "tagged check; visited is not the same as learned.</p></section>")
    return "".join(out)


def review_section(conn, now: str) -> str:
    due = conn.execute("SELECT COUNT(*) FROM review_items WHERE due_at <= ?", (now,)).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]
    upcoming = conn.execute("SELECT MIN(due_at) FROM review_items WHERE due_at > ?", (now,)).fetchone()[0]
    note = (f"{total} item{'s' if total != 1 else ''} scheduled"
            + (f"; next due {esc(upcoming)}" if upcoming else "")) if total else "No review items yet."
    return (f"<section><h2>Review due</h2><div class=\"stat\">{due}</div>"
            f"<p class=\"muted\">{note}</p></section>")


def practice_section(conn, goal) -> str:
    rows = [dict(r) for r in conn.execute(
        "SELECT s.id, s.started_at, g.title, COUNT(DISTINCT q.id) AS items, COUNT(a.id) AS answered,"
        " COALESCE(SUM(a.correct), 0) AS correct,"
        " SUM(CASE WHEN me.verdict = 'held' THEN 1 ELSE 0 END) AS held,"
        " SUM(CASE WHEN me.verdict = 'edge' THEN 1 ELSE 0 END) AS edge,"
        " SUM(CASE WHEN me.verdict = 'gap' THEN 1 ELSE 0 END) AS gap"
        " FROM sessions s JOIN goals g ON g.id = s.goal_id"
        " LEFT JOIN questions q ON q.session_id = s.id"
        " LEFT JOIN attempts a ON a.question_id = q.id"
        " LEFT JOIN mastery_evidence me ON me.attempt_id = a.id"
        " WHERE s.kind = 'practice' GROUP BY s.id ORDER BY s.id DESC LIMIT 20")]
    out = ["<section><h2>Practice history</h2>"]
    if not rows:
        out.append("<p class=\"empty\">No practice sets yet.</p></section>")
        return "".join(out)
    out.append("<table><tr><th>set</th><th>goal</th><th>answered</th><th>correct</th><th>evidence</th></tr>")
    for r in rows:
        out.append(
            f"<tr><td>#{r['id']}<br><span class=\"muted\">{esc((r['started_at'] or '')[:10])}</span></td>"
            f"<td>{esc(r['title'])}</td><td>{r['answered']}/{r['items']}</td><td>{r['correct']}</td>"
            f"<td><span class=\"tag t-held\">{r['held'] or 0}</span><span class=\"tag t-edge\">"
            f"{r['edge'] or 0}</span><span class=\"tag t-gap\">{r['gap'] or 0}</span></td></tr>")
    out.append("</table><p class=\"muted\">Counts from each set: evidence, not a mastery grade.</p></section>")
    return "".join(out)


def propositions_section(props: list[dict]) -> str:
    out = ["<section class=\"wide\"><h2>Propositions</h2>",
           "<p class=\"muted\">Status is about the field (is it sourced and accepted), not about the "
           "learner.</p>"]
    if not props:
        out.append("<p class=\"empty\">No propositions recorded yet.</p></section>")
        return "".join(out)
    for status in ("held", "edge", "candidate"):
        group = [p for p in props if p["status"] == status]
        out.append(f"<h2>{status} <span class=\"tag t-{status}\">{len(group)}</span></h2>")
        if not group:
            out.append("<p class=\"empty\">none</p>")
            continue
        out.append("<ul>" + "".join(
            f"<li>{esc(p['text'])} <span class=\"muted\">#{p['id']} · "
            f"{esc(p['source_ref'] or 'no source')}</span></li>" for p in group) + "</ul>")
    out.append("</section>")
    return "".join(out)


def resources_section(conn) -> str:
    rows = [dict(r) for r in conn.execute(
        "SELECT r.id, r.title, r.kind, r.pages, COUNT(c.id) AS chunks FROM resources r"
        " LEFT JOIN resource_chunks c ON c.resource_id = r.id GROUP BY r.id ORDER BY r.id DESC")]
    if not rows:
        return "<section><h2>Resources</h2><p class=\"empty\">No imported documents.</p></section>"
    items = []
    for r in rows:
        pages = f" · {r['pages']} pages" if r["pages"] else ""
        items.append(f"<li>{esc(r['title'])} <span class=\"muted\">#{r['id']} · {esc(r['kind'])}"
                     f"{pages} · {r['chunks']} chunks</span></li>")
    return "<section><h2>Resources</h2><ul>" + "".join(items) + "</ul></section>"


def serve(db: Path, goal_id: int | None, expected_version: int, now_fn, port: int = 0) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server API)
            url = urlparse(self.path)
            if url.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            raw_goal = parse_qs(url.query).get("goal", [None])[0]
            chosen = int(raw_goal) if raw_goal and raw_goal.isdigit() else goal_id
            try:
                body = render(db, chosen, expected_version, now_fn()).encode()
                status = 200
            except sqlite3.Error as exc:
                body = empty_state(f"Could not read the database: {exc}", db).encode()
                status = 500
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # Nothing on this page may load or run anything: no script, no remote fetch.
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; img-src data:")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep stdout to the one JSON line
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(json.dumps({"ok": True, "url": url, "db": str(db), "read_only": True,
                      "note": "serving until interrupted (Ctrl-C)"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

