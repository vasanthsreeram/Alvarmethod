---
name: probe
description: >
  Map the edge of the learner's understanding with a short graded quiz.
  Start broad, then binary-search every strand a lesson will need. Use when
  the user runs /probe or /skill:probe, or says quiz me, pretest, what do I
  already know, diagnose my understanding, probe me, or find the edge before
  teaching.
license: MIT
metadata:
  author: vasanthsreeram
  version: "1.0"
  source: "Eero Alvar — How I Use AI to Learn Things https://youtu.be/kzcI5F4tGiU"
---

# Probe

Measure first. Do not teach during a probe except a one-line correction after they answer.

**Quiz UI is mandatory.** Read [../teach/references/quiz-ui.md](../teach/references/quiz-ui.md) and call that tool. Never print A/B/C/D in the chat.

## Goal

Produce `.alvar/maps/<slug>.md` that labels every dependency strand:

`known` | `edge` | `unknown` | `blocked`

`blocked` = they said they don't know, or the question needs a tool you don't have.

## How to ask

- 1–3 multiple-choice questions per turn. Wait.
- Always include **D. I don't know** (or an extra "I don't know" option).
- Start wide (what kind of object is this? what does this operator measure?). Then split the strand that the answer leaves ambiguous.
- If they already listed solid ground, skip those strands.
- Invite a talk-through: a wrong reason + right letter is `edge`, not `known`.

One right answer. No trick options that hinge on wording. Put **I don't know** as an option. Do not mark the correct choice recommended.

## Scoring

| result | status move |
|--------|-------------|
| correct + sound reason | `known` |
| correct, thin reason | `edge` |
| wrong, near-miss | `edge` |
| wrong, foundation missing | `unknown` |
| I don't know | `blocked` or `unknown` |

After each batch, update the map. Stop when the upcoming lesson's dependencies are all labeled — not when you have asked "enough questions."

## Map file

Ids, statuses and the ledger follow [../teach/references/map.md](../teach/references/map.md). Strands
get ids `s1`, `s2`, … here and keep them for the life of the map; the teacher's plan nodes cite them
under `grounds:`.

Record each reading as you take it, so an interrupted probe loses nothing:

```bash
scripts/alvar session-create --goal "<goal>" --kind probe
scripts/alvar probe-record --strand s1 --status known --evidence "Q2, said \"rate of change\""
```

The Markdown map stays the readable export. The database is what the teacher resumed from.

```markdown
# Map — <goal>

Updated: <ISO date>
Goal: <one sentence>

## Strands
| id | strand | status | evidence |
|----|--------|--------|----------|
| s1 | … | known | Q2 + said "rate of change" |
| s2 | … | edge | Q4 correct, thin reason |

## Assessment
Read of the edge, in prose, three sentences at most: where this mind actually is, what the first
lesson may assume, and what will break if it is assumed.

## Quiz log
- Q1 [s1] <letter>, correct, "five words of their reason"
```

The strand list is the handoff. A teacher reads it and nothing else from the probe.

## End

Show the table, then the assessment. Say which strands a teacher should start from and which to
assume. Do not start the lesson unless they ask.
