# Runtime: SQLite memory for the skills

The skills hold the pedagogy. The runtime holds the state that must not depend on a model
remembering it: the plan, the tagged checks, the graph, and what the learner has actually shown.

Standard library Python only. No build step, no native SQLite driver, no server, no account.

## Where the data lives

```
<learning folder>/.alvar/
├── LEARNER.md          profile the skills already used
├── alvar.db            SQLite: structure and evidence (WAL)
├── maps/               readable strand + plan exports
├── sessions/           readable session logs
├── resources/          imported source files
├── visuals/            SVGs
├── exports/            JSON + graph.md
└── backups/            alvar-<timestamp>.db
```

`--data` or `$ALVAR_DATA_DIR` moves the whole directory, which is how one learning history spans
projects. Learner data never lives inside the skill installation directory, so reinstalling or
updating a skill cannot destroy it.

## Commands

One JSON object per invocation. `{"ok": false, ...}` exits 1 (or 2 for a usage/validation stop).

| command | job |
|---|---|
| `init` | create data dir, apply migrations, create the learner row (idempotent) |
| `doctor` | data-dir permissions, schema version (migrates an older database), integrity, WAL, backup age; each failure carries its exact `remedy` |
| `session-create --goal ... --kind teach\|probe` | open a session against a goal |
| `session-resume [--id N]` | events plus derived progress, for picking work back up |
| `probe-record --strand s1 --status known\|edge\|unknown\|blocked` | one strand reading, recorded as taken |
| `plan-create --file plan.json` | write the DAG from `{"nodes":[{id,title,claim,grounds}],"edges":[{from,to}]}` |
| `plan-validate` | unknown nodes, dangling edges, cycles |
| `plan-progress` | current and visited nodes, derived from tagged checks |
| `taught --node n1` | record that a step was taught |
| `check-record --node n1 --correct [--question ...]` | a tagged check; the node id is required, the wording is kept so practice never repeats it |
| `graph-add-proposition --text ... --status held --source ... [--quote ...]` | one claim; `resource:<id>#chunk=<n>` sources must name an imported resource |
| `graph-add-chain --conclusion N --premises A,B` | one argument, as a hyperedge |
| `graph-search --query ...` | keyword search with each hit's premises |
| `graph-export` / `export` | readable markdown, plus JSON |
| `mastery-record --verdict held\|edge\|gap` | what the learner showed, separate from knowledge |
| `import-markdown [--dir maps]` | read legacy `.alvar/maps/*.md` strand tables into the database (idempotent) |
| `backup` | consistent copy through SQLite's backup API |
| `practice-create --goal N [--count N]` | draft: held/edge targets plus every wording the learner has seen; writes nothing |
| `practice-create --goal N --file items.json` | validate and write agent-authored items into a new `practice` session |
| `practice-submit --question N --answer ... [--reasoning ...] [--confidence 0-1]` | grade one attempt; writes `attempts` + `mastery_evidence`, never a proposition |
| `practice-result --session N` | totals and verdicts for one set |
| `review-due [--limit N]` | review items due now, with the evidence that queued them |
| `review-record --item N --grade again\|hard\|good\|easy` | grade one retrieval; deterministic SM-2 reschedule, logged in `review_log` |
| `import-file <path> [--title ...]` | import `.md`/`.txt`/`.pdf` into `resources` + `resource_chunks` (page or byte offsets, sha256 dedupe); PDFs need `pdftotext` |
| `resource-search --query ...` | keyword search over imported chunks, with page and offsets |
| `propose-propositions --resource N` | candidate claims as JSON for the agent to review; writes nothing |
| `dashboard [--goal N] [--port N] [--out file.html]` | read-only HTML view served on `127.0.0.1` (free port by default) until interrupted; `--out` writes the file and exits |

Every mutation accepts `--idempotency-key`, so a retried agent tool call replays the stored result
instead of writing twice.

## The two rules the schema enforces

**Position is not completion.** A check carries the node id it is about. Current is the node on the
most recent tagged check; visited is the set of nodes that have appeared on any earlier one. There is
no done column and no done flag, so a failed check cannot un-finish a node, and a passed check cannot
finish one on its own.

**Knowledge is not understanding.** `propositions` and `reasoning_chains` describe the field.
`mastery_evidence` describes this learner. Recording a gap does not demote a proposition, and a
proposition being `held` does not mean the learner holds it. A wrong guess never becomes a
proposition.

## Practice, review, import, dashboard

**Practice** (`learn-practice`) runs in its own `practice` session. `practice-create` without `--file`
is a draft: held and edge propositions to target, plus every wording the learner has already seen.
The agent writes the items (answer key and rubric first) and `practice-create --file` validates them:
no repeated wording, no prompt that restates the proposition, no `candidate` targets, mcq keys must be
an option. `practice-submit` grades `mcq`/`exact`/`numeric` items against the key and takes the
agent's judgment for `open` ones; it writes `attempts` and `mastery_evidence` (correct and reasoned:
held; correct, no reasoning: edge; incorrect: gap) and never a proposition. `check-record` refuses
to run in a practice or review session, and commands that default to "the latest open session" only
consider teach and probe sessions.

**Review** (`learn-review`) queues one item per proposition, only from a practice gap or edge and
from `mastery-record --verdict edge`. New items come due a day later. `review-record` applies SM-2
(again, hard, good, easy map to quality 0, 3, 4, 5; intervals 1, 6, then interval x ease; ease floor
1.3) and logs the grade in `review_log`. `$ALVAR_NOW` pins the clock, so a schedule is reproducible.

**Import** (`learn-import`) stores `.md`/`.txt`/`.pdf` as `resources` (sha256, a copy under
`resources/`) and `resource_chunks` (about 1.5 KB each, with `page` for PDFs and
`start_offset`/`end_offset` in bytes). PDF text comes from `pdftotext` when it is installed; without
it the command refuses with `"missing_tool": "pdftotext"`. There is no OCR and no `.docx`.
`propose-propositions` prints candidate sentences with a `resource:<id>#chunk=<n>[&page=<p>]`
locator and writes nothing.

**Dashboard** (`learn-dashboard`) opens the database read-only (`mode=ro`) and serves one HTML page on
`127.0.0.1` (port 0 = a free port) until interrupted, re-rendering on every request. Inline CSS, a
hand-drawn SVG DAG, no JavaScript, no CDN, and a `Content-Security-Policy: default-src 'none'`
header. An absent or empty database renders an empty-state page; an older-schema database renders a
page asking for `alvar doctor`.

## Schema versions

Migrations in `runtime/db/migrations/` are additive and numbered; the runtime expects the newest.
Opening an older database (any command except `dashboard`) applies the missing migrations in place,
each in one transaction under the write lock, so two processes cannot both apply one. A database
newer than the runtime is refused with a message to update the skills.

| version | adds |
|---|---|
| 1 | the 18 base tables |
| 2 | practice item columns on `questions` (proposition, type, rubric, tolerance, distance), `attempts.feedback` |
| 3 | SM-2 state on `review_items`, `review_log` |
| 4 | resource size, pages, stored copy; chunk byte offsets |

## Install

`./install.sh` copies each skill, and for every skill that ships `scripts/alvar` (`teach`,
`learn-graph`, `learn-practice`, `learn-review`, `learn-import`, `learn-dashboard`) also bundles
`runtime/` inside the skill so the installed copy works without this repo. The launcher resolves, in
order: `$ALVAR_RUNTIME`, `<skill>/runtime/`, `../../../runtime/` (repo checkout),
`$PWD/.alvar-runtime`.

Installing through a tool that copies `skills/` only (for example `npx skills add ...`) does not
bundle the runtime; set `ALVAR_RUNTIME` to a checkout's `runtime/` directory in that case.

## Tests

```bash
python3 tests/test_runtime.py     # 28 tests, ~20 s, no network
```

Covers: idempotent init, doctor, probe recording, plan validation (unknown nodes, dangling edges,
cycles), position-not-completion, required node ids, hyperedge chains, mastery separation,
idempotency replay, legacy markdown import (twice, to prove no duplication), eight concurrent
writers keeping integrity and unique sequence numbers, an abrupt process death inside a
transaction, export and backup.

Since the practice to release phases: practice drafting, item rejection, grading into attempts and
evidence with propositions and plan position untouched, practice sessions refusing checks; review
queueing only from failures and edge evidence, a deterministic five-step SM-2 schedule; text import
byte offsets and dedupe, PDF pages (skipped if `pdftotext` is absent), the missing-tool refusal,
unsupported types; the dashboard's empty state and its live, read-only, script-free page; a v1
database migrated and still readable, a newer database refused, doctor's permission and backup-age
remedies; and the installed layout running from its bundled runtime with no repo.

The importer handles both map shapes the skills have shipped: the older three-column table (strand,
status, evidence) with ids assigned in file order, and the newer table with an explicit `s` id
column. Verified on the real `alvar-learning` map: 9 strands recorded, 9 skipped on the re-run.

## Not in this release

Voice (`learn-voice`), OCR and `.docx`/image import, FSRS scheduling, graph merge and duplicate
detection, a zoomable graph view, and data deletion. Tested on Linux with Python 3.11; the
per-harness skill discovery (Pi, Claude Code, Codex, OpenCode) has not been re-tested for the new
skills.
