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
| `doctor` | schema version, integrity check, pragmas, table count |
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

## Install

`./install.sh` copies each skill, and for `teach` and `learn-graph` also bundles `runtime/` inside the
skill so the installed copy works without this repo. The launcher resolves, in order:
`$ALVAR_RUNTIME`, `<skill>/runtime/`, `../../../runtime/` (repo checkout), `$PWD/.alvar-runtime`.

## Tests

```bash
python3 tests/test_runtime.py     # 12 tests, ~7 s, no network
```

Covers: idempotent init, doctor, probe recording, plan validation (unknown nodes, dangling edges,
cycles), position-not-completion, required node ids, hyperedge chains, mastery separation,
idempotency replay, legacy markdown import (twice, to prove no duplication), eight concurrent
writers keeping integrity and unique sequence numbers, an abrupt process death inside a
transaction, export and backup.

The importer handles both map shapes the skills have shipped: the older three-column table (strand,
status, evidence) with ids assigned in file order, and the newer table with an explicit `s` id
column. Verified on the real `alvar-learning` map: 9 strands recorded, 9 skipped on the re-run.

## Not in this release

Practice generation and grading (`learn-practice`), spaced repetition scheduling (`learn-review`),
document ingestion (`learn-import`), the browser dashboard (`learn-dashboard`), and voice
(`learn-voice`). The schema already carries `questions`, `attempts`, `review_items`, `resources`,
`resource_chunks` and `jobs` so those phases can land without a migration of existing data.
