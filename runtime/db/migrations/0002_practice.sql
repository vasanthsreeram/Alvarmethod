-- Alvarmethod runtime schema, migration 2: practice items.
-- A practice item is a question row tied to the proposition it exercises, with its
-- answer key and rubric written before the learner sees it. Additive only.

ALTER TABLE questions ADD COLUMN proposition_id INTEGER REFERENCES propositions(id) ON DELETE SET NULL;
ALTER TABLE questions ADD COLUMN item_type TEXT;          -- 'mcq' | 'exact' | 'numeric' | 'open'
ALTER TABLE questions ADD COLUMN rubric TEXT;             -- what a sound answer must show
ALTER TABLE questions ADD COLUMN tolerance REAL;          -- numeric items only
ALTER TABLE questions ADD COLUMN distance TEXT;           -- 'familiar' | 'adjacent' | 'unfamiliar'

ALTER TABLE attempts ADD COLUMN feedback TEXT;

CREATE INDEX IF NOT EXISTS idx_questions_session ON questions(session_id);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
