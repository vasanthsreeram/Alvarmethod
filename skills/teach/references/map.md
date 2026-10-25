# The map: strands, the plan DAG, and the graph

Three artifacts, three timescales. A strand read is what the probe produces. The plan DAG is what
the teacher walks this session. The graph is what survives the session.

All three are written under `.alvar/`, use the same id vocabulary, and are plain markdown so a human
can read them and an agent can parse them without a schema library.

Source for this model: LearnHarness (AGPL-3.0, github.com/amosblomqvist/learnharness), specifically
its plan-tree and probe-assessment contracts. The rules below are re-derived for a file-based skill
pack with no server and no UI.

## 1. Ids and records

- **Strands** are the dependency questions a lesson rests on. Ids are `s1`, `s2`, … Stable for the
  life of the map. A strand is never renumbered; a wrong strand is struck through, not deleted.
- **Nodes** are the reasoning steps of the plan. Ids are `n1`, `n2`, … Assigned once, never reused,
  never renumbered. Inserting a prerequisite takes the next free number, so order on the page is not
  the id order and does not need to be.
- **Edges** run from a prerequisite to the node that needs it. Only that direction. Any edge that
  cannot be stated as "you cannot do B before A" is not an edge.

A node record:

```markdown
### n4 — Rates multiply through composed steps
- grounds: s2 (known), s5 (edge)
- edges: n2 -> n4, n3 -> n4
- check: tagged quiz, one per node
- state: visited
```

A strand record:

```markdown
| s2 | What a derivative measures | known | Q3 + said "instantaneous rate" |
```

## 2. Position, not completion

The sharpest rule in the source model, and the one worth copying exactly:

> **A quiz tagged with a node id is a position signal. It is never a completion signal.**

- **Current node** = the node on the most recent tagged check, whatever the answer. An answer, right
  or wrong, says where the lesson is, not what is finished.
- **Visited** = every node that has appeared on an earlier tagged check. Sticky and monotonic. A node
  does not become unvisited because a later answer was wrong.
- **No done ledger.** There is no `done: true` field anywhere, and no bookkeeping of completion. If a
  file says `state: done`, it is derived from a tagged check and the learner's progress, never stored
  as a fact by itself.
- **A failed check moves nothing.** It triggers a re-teach or an inserted prerequisite. It does not
  mark a node incomplete, because that state did not exist.
- **The teacher moving to a new node is the judgement that the previous one is finished.** Not the
  quiz result. A node may carry several checks over several turns.
- **No fallback current.** Before the first tagged check there is no current node. Do not guess one
  from the edges.

Practical consequence for a skill pack with no server: the session file must record every tagged
check, in order, with its node id. Current and visited are then computed by reading the log, not by
maintaining flags.

## 3. Plan movement

Three moves, nothing else:

| move | when | effect |
|---|---|---|
| `advance` | the learner holds the step well enough to build on | next node by topological order |
| `insert` | the check exposes a missing prerequisite | new node, next free id, edges into the stuck node |
| `revisit` | an earlier step turned out not to hold | move back with a tagged check on that node |

Freeze the plan after presenting it. Only a check result may change it. Anything else is the learner
asking, which is a different conversation: answer, then resume.

## 4. Ledger

One line per event, in the session file, in order. These are the only events.

```markdown
- probe s2 wrong, foundation missing -> unknown
- check n4 correct, reason sound
- check n4 wrong, said "slope of the line" -> insert n7
- taught n7 (2 turns)
```

The log is append-only. Rewriting history to make a lesson look cleaner is the one thing that makes
a map untrustworthy. If an entry was wrong, add a correction line.

## 5. The graph, across sessions

The plan dies with the session. The graph does not.

`.alvar/graph.md` holds what was actually established, as propositions and the reasoning chains that
carry them:

```markdown
## Proposition
A derivative is a rate: change in output per unit change in input at a point.
- chain: limit of a difference quotient -> instantaneous rate -> slope at a point
- source: sessions/2026-08-16-calculus.md, n4
- status: held (checks n4, n6 correct with sound reasons)
```

Rules:

- One proposition per heading. If it cannot be stated in one sentence a learner could deny, it is not
  a proposition yet.
- The chain lists the premises it rests on, in order. A proposition whose chain is missing stays
  `candidate`.
- `source:` names the session file and node id. A proposition with no source is a guess and is
  marked `candidate`.
- Status is `held`, `edge`, or `candidate`. Only `held` may be assumed at the start of a new session.
- Append. Do not rewrite earlier propositions when a lesson goes differently; add a new one and note
  the contradiction.

At the start of a new session on a related goal, read the graph before probing. Skip strands whose
propositions are `held`, and say which ones you skipped. That is the whole point of keeping it.

## 6. What goes where

| file | holds | lifetime |
|---|---|---|
| `.alvar/maps/<slug>.md` | strands + status + the session's plan DAG | one goal |
| `.alvar/sessions/<date>-<slug>.md` | ledger, the steps as taught, the tagged checks | one session |
| `.alvar/graph.md` | propositions + chains + sources | forever |
| `.alvar/LEARNER.md` | how this person learns, voice, what they hold | forever |

A map is fresh if the goal is the same and nothing in the graph contradicts it. Otherwise probe again.
