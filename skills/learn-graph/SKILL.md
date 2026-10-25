---
name: learn-graph
description: >
  Read and write the persistent knowledge graph: propositions, reasoning chains,
  and the evidence of what the learner has actually shown. Use when the user runs
  /learn-graph or asks what they already know on a topic, wants a proposition added
  or corrected, wants the chain behind a claim, or when teach needs to skip strands
  the graph already holds.
license: MIT
metadata:
  author: vasanthsreeram
  version: "1.0"
  source: "LearnHarness graph model — propositions, reasoning chains, mastery evidence"
---

# Learn graph

The graph is what survives a session. It holds two separate things, and mixing them is the one
mistake that ruins it:

- **Knowledge**: propositions and the chains that carry them. True or false about the world.
- **Understanding**: mastery evidence. What this learner has shown, from which attempt.

A proposition appearing in a lesson never implies the learner holds it. Only `mastery-record` says
that, and it names the attempt or the node it came from.

Full schema and rules: [references/schema.md](references/schema.md).

## Commands

All commands return one JSON object. Run them with the launcher shipped beside this skill:

```bash
scripts/alvar init                      # first run in a learning folder
scripts/alvar graph-search --query "rate of change"
scripts/alvar graph-add-proposition --text "..." --status held --source "sessions/2026-10-25-calculus.md#n4"
scripts/alvar graph-add-chain --conclusion 12 --premises 9,10
scripts/alvar graph-export              # writes .alvar/exports/graph.md
scripts/alvar mastery-record --verdict held --proposition 12 --node n4 --note "check 2, sound reason"
```

## Rules

- **One proposition per sentence.** If the learner could not deny it, it is a description, not a
  proposition.
- **A chain is a hyperedge.** List every premise the inference needed. Do not split a joint
  inference into separate one-premise implications, and do not add a premise that was not used.
- **Status is about knowledge, not about the learner.** `held` means the field accepts it and a
  source backs it. `candidate` means no source yet.
- **Never record a learner guess as a proposition.** A wrong answer goes in mastery evidence with
  `verdict gap`, never into the proposition table.
- **Always carry provenance.** `--source` takes `sessions/<file>.md#n<id>` or a resource locator. A
  `held` proposition with no source is downgraded to `candidate` on export.
- **Append, never rewrite.** If a lesson contradicts an earlier proposition, add the new one and
  note the contradiction in `--note`. History stays recoverable.

## What to do at the start of a lesson

`graph-search` the goal's keywords, then say plainly which strands you are skipping because the
graph already holds them, and which are `candidate` and therefore still need probing. Silence here
is how a learner gets re-taught what they already know.
