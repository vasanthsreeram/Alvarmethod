---
name: learn-review
description: >
  Spaced retrieval of what the learner already got wrong or only half held:
  practice failures and edge evidence come back on an SM-2 schedule. Use when the
  user runs /learn-review, asks what is due, wants to review or revise, or at the
  start of a teach session when review-due reports items due.
license: MIT
metadata:
  author: vasanthsreeram
  version: "1.0"
  source: "SM-2 (Wozniak, 1990) — transparent interval and ease scheduling"
---

# Learn review

A review asks the learner to **retrieve** something they were taught and did not fully hold. It is
short, it is about one idea at a time, and it never teaches anything new.

## Where items come from

The runtime queues an item, one per proposition, only from evidence:

- a practice attempt graded `gap` or `edge` (`practice-submit`), and
- `mastery-record --verdict edge` against a proposition.

Nothing else creates review items. Not every proposition, not a teach-time `gap` (that idea was never
taught, so it needs teaching, not retrieval), and not anything you would like the learner to know.
A new `gap` on an item already queued counts as a lapse and resets it to one day.

## Commands

```bash
scripts/alvar review-due                       # items due now, oldest first, with what went wrong last time
scripts/alvar review-due --limit 5
scripts/alvar review-record --item 12 --grade good     # again | hard | good | easy
```

## What a review session looks like

1. `review-due`. If `due` is 0, say so and when the next item is due (`next_due_at`). Stop.
2. Take at most five items. For each one:
   - Read `text` and `last_evidence` (the earlier prompt and the wrong answer).
   - Ask **one new retrieval question** about that proposition through the harness question tool.
     Use a different wording and, where it fits, a different context from the earlier prompt. Ask
     for the reasoning.
   - Grade it honestly:

     | grade | when |
     |---|---|
     | `again` | wrong, or right by luck with no reasoning |
     | `hard` | right, but slow, or needed a hint |
     | `good` | right, with sound reasoning |
     | `easy` | right at once, reasoning complete, would bore them to see it soon |

   - `review-record --item N --grade ...`. The reply carries the next due date.
3. Close with one line per item: what came back and what did not.

## Rules

- **A review never introduces new material.** If the learner cannot retrieve it because a
  prerequisite is missing, stop the review for that item, say so, and hand it to `teach` as an
  inserted node. Do not teach it inside the review.
- **A review never moves plan position.** Do not call `check-record` during a review.
- **A grade is about this retrieval.** It reschedules the item; it is not a mastery claim and it
  never changes a proposition.
- Schedules are deterministic SM-2 (`sm2-v1`): same state and grade, same next date. Every grade is
  kept in `review_log`, so a schedule can be replayed or audited.
