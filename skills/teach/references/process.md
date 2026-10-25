# Probe → Plan → Teach

Source: Eero Alvar, *How I Use AI to Learn Things*
https://youtu.be/kzcI5F4tGiU

Load this after `philosophy.md`. Do not skip phases unless the learner already has a fresh map for this exact goal.

## Phase 1 — Probe

Measure the edge of understanding before teaching.

- Start broad, then binary-search every strand the lesson will depend on.
- Use graded multiple-choice (include "I don't know") through the **harness quiz UI** — see [quiz-ui.md](quiz-ui.md). Never dump A/B/C/D in chat.
- Ask 1–3 questions at a time. Wait for the tool. Do not dump a long exam.
- Let the learner talk through reasoning in a note or in chat. Treat that as signal.
- If they already stated solid ground, skip those strands.
- Write the map to `.alvar/maps/<topic>.md`.
- A long probe is a feature when context is thin. It is also a warm-up.

Stop when each dependency strand is labeled `known`, `edge`, `unknown`, or `blocked`.

## Phase 2 — Plan

Reason how to teach **this mind** **this goal**. Do not wing it.

- Build a dependency DAG. Each node is one reasoning step, not a chapter.
- Start from `known`. Path through `edge`. Do not start in `unknown` with no ramp.
- Give every strand an id (`s1`, `s2`, …) and every node an id (`n1`, `n2`, …). Ids are assigned once and never renumbered; a new prerequisite takes the next free number.
- Each node states its `grounds:` (the strand ids it rests on) and its `edges:`. An edge runs prerequisite → dependent, and nothing else.
- Verify claims the plan will treat as fact (use `learn-verify` when the domain is empirical, historical, or you are unsure). Math still gets a pass for named theorems if you would otherwise invent them.
- Show the plan as a mermaid graph **before** teaching, labelled with the node ids. Two jobs: the learner sees what is coming; the graph forces you to finish the reasoning.
- Write the strands and the DAG into `.alvar/maps/<topic>.md` and the plan into `.alvar/sessions/<date>-<topic>.md`, per [map.md](map.md).
- Ask if they want the graph changed. Then freeze it until a check forces a new node.

## Phase 3 — Teach

Walk the DAG. One node per turn.

- One reasoning step. Stop. Do not rush the whole graph (that is the ChatGPT failure mode).
- If a picture would lock the idea, use `learn-visual` (or write an SVG and look at it).
- After the step, quiz that step, tagged with the node id. Three reasons: they cannot gaslight themselves; you stay calibrated; applying the idea is how it locks in.
- Advance only on lock-in. The tagged check says where the lesson is; your judgement, not the score, decides when a node is finished. A failed check moves nothing: stay, or insert a prerequisite node.
- Current and visited are read from the ledger, not stored as flags. Do not keep a done list.
- Accept questions mid-step. Do not "finish the lesson" over them.
- Give them things they can accept at face value only after the step they rest on is locked.
- Persist every check as one ledger line in the session file, and every established proposition to `.alvar/graph.md` when the session ends.

## Feedback rules

- Quiz after every node, not "at the end."
- Prefer a short applied question over a recap prompt.
- If they answer from vibe, ask one tighter question before advancing.

## What the system absorbs

You handle: order, sources, verification, "what next," file logging, diagrams.

They handle: thinking about the material.
