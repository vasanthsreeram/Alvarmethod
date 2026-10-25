# Graph schema

The database is one SQLite file in the learner data directory: `.alvar/alvar.db`. Authoritative SQL
is `runtime/db/migrations/0001_init.sql`. This page says what each table means and which commands
write it.

## Two kinds of record, kept apart on purpose

| table | holds | written by |
|---|---|---|
| `propositions` | objective domain knowledge | `graph-add-proposition` |
| `reasoning_chains`, `chain_premises` | arguments, as hyperedges | `graph-add-chain` |
| `mastery_evidence` | observations about this learner | `mastery-record` |
| `attempts` | the raw answer, reasoning, confidence, result | recorded during a session |

A proposition can be `held` while the learner has no mastery evidence for it, and a learner can have
`gap` evidence against a proposition that is still `held` in the field. Those are different facts and
they stay in different tables. Nothing derives one from the other.

## Reasoning chains are hyperedges

One argument frequently needs several premises jointly. `reasoning_chains` holds the conclusion, and
`chain_premises` holds every premise with its position. Splitting a joint inference into independent
one-premise implications changes the logic and is not allowed.

```
propositions 9  "a limit is a value approached"
propositions 10 "a difference quotient is an average rate"
propositions 12 "the derivative is the limit of the difference quotient"
reasoning_chains 1 -> conclusion 12
chain_premises   (1, 9, pos 1), (1, 10, pos 2)
```

## Status vocabulary

- `held`: the field accepts it and provenance names a source.
- `edge`: accepted but the learner's grip is thin, or the source is weaker than you would like.
- `candidate`: not yet established, or no source. Never assumed at the start of a lesson.

Mastery verdicts are separate: `held`, `edge`, `gap`.

## Provenance

`provenance` records `entity` (`proposition`, `resource_chunk`, `artifact`), a `kind` (`url`, `file`,
`session`), the locator, and an optional quote. `graph-add-proposition --source` writes a session
provenance row automatically. A `held` proposition without provenance is a claim pretending to be
knowledge; export flags it.

## Plan nodes versus propositions

`plan_nodes` are lesson structure for one goal. `propositions` are knowledge. A node is one reasoning
step in this lesson; a proposition is a claim about the world. The plan can be thrown away and
rewritten; the graph cannot, and is not rewritten when a lesson goes differently.

## Pragmas and recovery

WAL, foreign keys on, `busy_timeout` 5000. `alvar backup` takes a consistent copy through SQLite's
backup API. `alvar doctor` reports integrity, schema version and pragmas. `alvar export` writes JSON
plus the readable `graph.md`.
