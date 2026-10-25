---
name: learn-dashboard
description: >
  Open a local, read-only browser view of the learner's state: the lesson DAG with
  the current node, propositions by status, practice history and reviews due. Use
  when the user runs /learn-dashboard, asks to see their progress, their plan, or
  their graph in a browser, or wants a picture of where they are.
license: MIT
metadata:
  author: vasanthsreeram
  version: "1.0"
---

# Learn dashboard

A window onto the same database the agent writes. It shows; it never changes anything. All teaching,
practice and review still happen in the terminal.

## Launch

```bash
scripts/alvar dashboard                  # serves on 127.0.0.1, a free port; prints {"url": ...}
scripts/alvar dashboard --goal 3         # open on a specific goal
scripts/alvar dashboard --port 8765      # fixed port
scripts/alvar dashboard --out page.html  # write the HTML file and exit, no server
```

`dashboard` prints one JSON line with the `url`, then keeps serving until interrupted (Ctrl-C, or
stop the background process). Run it in the background, give the learner the URL, and leave it
running; every reload re-reads the database, so it stays current while you teach.

It binds to `127.0.0.1` only. There is no build step and nothing to install: the page is one HTML
file with inline CSS and a hand-drawn SVG, no JavaScript, no CDN, and a Content-Security-Policy that
forbids loading anything.

## What it shows

- **Lesson plan**: the DAG for the goal. The current node (the one on the most recent tagged check)
  is highlighted, visited nodes are solid, upcoming nodes are faint and dashed. Visited means the
  lesson reached it, not that it was learned.
- **Propositions**, grouped `held`, `edge`, `candidate`, with their sources. That status is about the
  field, not about the learner.
- **Practice history**: each set, answered and correct counts, and the held/edge/gap evidence it
  produced. Counts, not mastery grades.
- **Review due**: how many items are due now and when the next one is.
- **Resources**: imported documents and their chunk counts.

An empty or brand-new data directory shows an empty-state page, not an error. A database from an
older runtime shows a page asking for `alvar doctor` (which migrates it); the dashboard never
migrates or writes on its own.

## Rules

- **Read-only.** The database is opened in SQLite read-only mode. To change anything, use the
  other skills' commands.
- **Do not describe the page as a grade.** If the learner asks "am I done?", answer from evidence
  (checks, practice, reviews), not from how much of the DAG is solid.
- Do not expose it beyond the local machine. If the learner wants to share progress, use `alvar
  export` and send the file.
