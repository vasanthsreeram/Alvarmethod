---
name: learn-practice
description: >
  Independent practice on what the learner has already been taught: new problems
  drawn from held and edge propositions in the graph, graded against an answer key
  written before the learner sees the item. Use when the user runs /learn-practice,
  asks to practise, wants exercises or a problem set on a past topic, or when teach
  finishes a goal and offers practice.
license: MIT
metadata:
  author: vasanthsreeram
  version: "1.0"
  source: "LearnHarness practice model — independent problems, immutable keys, rubrics (reimplemented, no code reuse)"
---

# Learn practice

Practice checks whether what was taught travels. A practice item is a **new problem about an old
fact**: different numbers, a different context, a different direction of reasoning. Asking the
lesson's check again only measures recall of wording.

Practice never moves the lesson plan. It runs in its own session (`kind = practice`), and
`check-record` refuses to run inside one.

## When to run

- The learner asks to practise, or wants exercises on something they learned before.
- A teach session finished a goal: offer one short set (3 to 5 items), do not force it.
- A review turned up a gap and the learner wants more than one retrieval on it.

Do not run practice on a goal that was never taught. If `practice-create` returns no targets, say
so and offer `teach` instead.

## Steps

```bash
scripts/alvar practice-create --goal 3 --count 4          # draft: targets + wordings to avoid, writes nothing
scripts/alvar practice-create --goal 3 --count 4 --file items.json
scripts/alvar practice-submit --question 41 --answer "B" --reasoning "2 over 8" --confidence 0.7
scripts/alvar practice-submit --question 42 --answer "..." --reasoning "..." --incorrect --feedback "named the slope, not the limit"
scripts/alvar practice-result --session 9
```

1. **Draft.** `practice-create --goal N` returns `targets` (held and edge propositions, weakest
   evidence first, goal-linked first) and `avoid` (every question wording this learner has already
   seen). Nothing is written.
2. **Write the items yourself**, one JSON object each:

   ```json
   {"items": [
     {"proposition_id": 7, "item_type": "mcq",
      "prompt": "A ramp climbs 2 m over 8 m of floor. What is its slope?",
      "options": ["4", "0.25", "16"], "answer_key": "0.25",
      "rubric": "divides rise by run", "distance": "adjacent"}
   ]}
   ```

   - Vary the problem, not the fact. Change the context, the numbers, or ask the learner to find a
     faulty premise or combine two propositions. The runtime rejects a prompt that repeats a seen
     wording, and one that contains the proposition's own sentence.
   - Write the `answer_key` and `rubric` now, before the learner answers. They are immutable.
   - `item_type`: `mcq` (key must be one of the options, verbatim), `exact`, `numeric` (with
     `tolerance`), or `open` (you judge it against the rubric).
   - `distance`: `familiar`, `adjacent`, or `unfamiliar` context. Mix them; start nearer.
3. **Ask one item at a time** through the harness question tool (see teach's `quiz-ui.md`). Ask for
   the reasoning and a confidence before showing anything.
4. **Submit** each answer as given. `mcq`, `exact` and `numeric` are graded by the runtime against
   the key; if you pass `--correct` or `--incorrect` and it disagrees with the key, the runtime
   refuses. `open` items need your judgment against the rubric.
5. **Report** with `practice-result`.

## How grading writes evidence

Each submission writes one `attempts` row (raw answer, reasoning, confidence, correct) and one
`mastery_evidence` row tied to that attempt:

| attempt | verdict |
|---|---|
| correct, with reasoning | `held` |
| correct, no reasoning | `edge` |
| incorrect | `gap` |

You may lower a verdict with `--verdict` (correct answer, broken reasoning: `edge`). You may never
raise one to `held` without a correct, reasoned answer.

**Grading never writes a proposition.** A wrong answer is a fact about this learner, not about the
field. If the learner's answer reveals the proposition itself is wrong, verify it with
`learn-verify` and add a corrected proposition through `learn-graph`, with a source.

## How to report results

Say what the set showed, item by item, in plain words: which ideas carried to a new context and
which did not. A score is a count of items from one set, not a mastery grade:

- Good: "Two of three carried over. The limit idea broke on the numeric item: you computed the
  secant slope but did not shrink h."
- Not this: "You've mastered derivatives (67%)."

Then offer the next move: a review later for the gaps, an inserted prerequisite in `teach`, or
nothing.
