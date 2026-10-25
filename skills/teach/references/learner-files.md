# Learner files

All session state lives in the **learner's working directory**, not in this skill repo.

```
.alvar/
  LEARNER.md                 # how this mind wants to be taught
  graph.md                   # propositions + reasoning chains, carried across sessions
  maps/<slug>.md             # probe strands + the plan DAG for one goal
  sessions/<date>-<slug>.md  # plan + steps + tagged checks + ledger
  visuals/<slug>-<n>.svg     # diagrams from learn-visual
```

Create `.alvar/` on first use.

## LEARNER.md

If missing, run `learn-profile` or write a stub from `assets/LEARNER.md` and ask 3–5 questions to fill it. Do not invent a personality.

Read LEARNER.md at the start of every `teach` session. It controls:

- voice and density
- how they want struggle
- what they already treat as solid
- whether they want visuals, mermaid, LaTeX, or a long markdown log

## Map file

Full rules in [map.md](map.md). Shape:

```markdown
# Map — <goal>

Updated: <ISO date>
Goal: <one sentence>

## Strands
| id | strand | status | evidence |
|----|--------|--------|----------|
| s1 | line integrals | known | Q2 correct, explained work |
| s2 | Stokes | edge | recognized statement, missed Faraday link |
| s3 | differential forms | unknown | said so |
| s4 | SR field mix | blocked | answered "I don't know" |

Status: `known` | `edge` | `unknown` | `blocked`

## Assessment
Three sentences: where this mind is, what the first lesson may assume, what breaks if it does.

## Plan
| id | node | grounds | edges |
|----|------|---------|-------|
| n1 | covector as a machine | s1, s3 | n1 -> n2 |
| n2 | 1-form | s2 | n2 -> n3 |

## Quiz log
- Q1 [s1] C, correct, "work done along the path"
```

## Session file

```markdown
# Session — <goal>
Date:
Model:
Goal:

## Plan
\`\`\`mermaid
graph TD
  n1[covector as a machine] --> n2[1-form]
  n2 --> n3[wedge]
\`\`\`

## Ledger
- probe s2 wrong, foundation missing -> unknown
- taught n1 (2 turns)
- check n1 correct, "it eats a vector and returns a number"

## Log
### Node: n1 covector as a machine
- taught:
- visual:
- check: tagged n1
- result: advance | retry | insert-prereq
```

Current and visited are read from the ledger, never stored as flags.

Keep these files updated as you go. They are the persistence layer (the portable stand-in for a markdown-log / Obsidian pane).
