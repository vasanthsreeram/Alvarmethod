-- Alvarmethod runtime schema, migration 3: spaced repetition.
-- review_items get SM-2 state and a pointer to the evidence that created them;
-- review_log keeps every grade so a schedule can be replayed. Additive only.

ALTER TABLE review_items ADD COLUMN source_kind TEXT;           -- 'practice' | 'mastery'
ALTER TABLE review_items ADD COLUMN source_id INTEGER;          -- mastery_evidence.id that created it
ALTER TABLE review_items ADD COLUMN reps INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_items ADD COLUMN lapses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE review_items ADD COLUMN last_grade TEXT;
ALTER TABLE review_items ADD COLUMN algorithm TEXT NOT NULL DEFAULT 'sm2-v1';
ALTER TABLE review_items ADD COLUMN created_at TEXT;

-- One schedule per learner and proposition; new evidence updates it, never duplicates it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_unique ON review_items(learner_id, proposition_id);

CREATE TABLE IF NOT EXISTS review_log (
    id               INTEGER PRIMARY KEY,
    review_item_id   INTEGER NOT NULL REFERENCES review_items(id) ON DELETE CASCADE,
    grade            TEXT NOT NULL CHECK (grade IN ('again','hard','good','easy')),
    interval_before  REAL NOT NULL,
    interval_after   REAL NOT NULL,
    ease_before      REAL NOT NULL,
    ease_after       REAL NOT NULL,
    due_at           TEXT NOT NULL,
    algorithm        TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_log_item ON review_log(review_item_id);
