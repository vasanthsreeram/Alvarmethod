-- Alvarmethod runtime schema, migration 1.
-- One local SQLite database per learner data directory. WAL, foreign keys on.
-- Knowledge (propositions/chains) is stored separately from learner understanding
-- (mastery_evidence). See docs/runtime.md.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learners (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    display     TEXT,
    profile_ref TEXT,                       -- path to LEARNER.md
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goals (
    id          INTEGER PRIMARY KEY,
    learner_id  INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    slug        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dropped')),
    created_at  TEXT NOT NULL,
    UNIQUE (learner_id, slug)
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'teach' CHECK (kind IN ('probe','teach','practice','review')),
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    model       TEXT,
    resumed_from INTEGER REFERENCES sessions(id)
);

-- Append-only. Every probe answer, check, judgment and plan move lands here.
-- Current and visited plan nodes are derived by reading this table, never stored
-- as flags: a tagged check is a position signal, not a completion signal.
CREATE TABLE IF NOT EXISTS session_events (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN
                ('probe','check','taught','plan','insert','revisit','note')),
    strand_key  TEXT,
    node_key    TEXT,
    outcome     TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (session_id, seq)
);

CREATE TABLE IF NOT EXISTS plan_nodes (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    node_key    TEXT NOT NULL,              -- 'n1', 'n2', assigned once, never renumbered
    title       TEXT NOT NULL,
    claim       TEXT,
    grounds     TEXT,                       -- comma list of strand keys it rests on
    created_at  TEXT NOT NULL,
    UNIQUE (goal_id, node_key)
);

CREATE TABLE IF NOT EXISTS plan_dependencies (
    id          INTEGER PRIMARY KEY,
    goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    from_node   TEXT NOT NULL,              -- prerequisite
    to_node     TEXT NOT NULL,              -- dependent
    UNIQUE (goal_id, from_node, to_node),
    CHECK (from_node <> to_node)
);

CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    node_key    TEXT,
    strand_key  TEXT,
    prompt      TEXT NOT NULL,
    options     TEXT,                       -- JSON array
    answer_key  TEXT NOT NULL,              -- immutable once written
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempts (
    id          INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    learner_id  INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    answer      TEXT,
    reasoning   TEXT,
    confidence  REAL,
    correct     INTEGER,                    -- 0/1/NULL while ungraded
    raw         TEXT,                       -- preserve what the learner actually said
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS propositions (
    id          INTEGER PRIMARY KEY,
    learner_id  INTEGER REFERENCES learners(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'candidate'
                CHECK (status IN ('held','edge','candidate')),
    source_ref  TEXT,                       -- 'sessions/<file>.md#n4'
    created_at  TEXT NOT NULL
);

-- One argument = one row plus its premises. A single premise must not be split out
-- into an independent implication when the inference needed all of them jointly.
CREATE TABLE IF NOT EXISTS reasoning_chains (
    id            INTEGER PRIMARY KEY,
    conclusion_id INTEGER NOT NULL REFERENCES propositions(id) ON DELETE CASCADE,
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chain_premises (
    id           INTEGER PRIMARY KEY,
    chain_id     INTEGER NOT NULL REFERENCES reasoning_chains(id) ON DELETE CASCADE,
    premise_id   INTEGER NOT NULL REFERENCES propositions(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    UNIQUE (chain_id, premise_id)
);

CREATE TABLE IF NOT EXISTS provenance (
    id          INTEGER PRIMARY KEY,
    entity      TEXT NOT NULL,              -- 'proposition' | 'resource_chunk' | 'artifact'
    entity_id   INTEGER NOT NULL,
    kind        TEXT NOT NULL,              -- 'url' | 'file' | 'session'
    locator     TEXT NOT NULL,
    quote       TEXT,
    created_at  TEXT NOT NULL
);

-- What the learner has shown. Never inferred from a proposition merely appearing
-- in a lesson: that separation is the point of this table.
CREATE TABLE IF NOT EXISTS mastery_evidence (
    id            INTEGER PRIMARY KEY,
    learner_id    INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    proposition_id INTEGER REFERENCES propositions(id) ON DELETE SET NULL,
    node_key      TEXT,
    attempt_id    INTEGER REFERENCES attempts(id) ON DELETE SET NULL,
    verdict       TEXT NOT NULL CHECK (verdict IN ('held','edge','gap')),
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_items (
    id            INTEGER PRIMARY KEY,
    learner_id    INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    proposition_id INTEGER REFERENCES propositions(id) ON DELETE CASCADE,
    due_at        TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 1,
    ease          REAL NOT NULL DEFAULT 2.5,
    last_reviewed TEXT
);

CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY,
    learner_id  INTEGER REFERENCES learners(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    kind        TEXT NOT NULL,              -- 'pdf' | 'md' | 'txt' | 'url'
    locator     TEXT NOT NULL,
    sha256      TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_chunks (
    id          INTEGER PRIMARY KEY,
    resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL,
    page        INTEGER,
    text        TEXT NOT NULL,
    UNIQUE (resource_id, ordinal)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    kind        TEXT NOT NULL,              -- 'svg' | 'mermaid' | 'demo'
    locator     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued','running','done','failed')),
    payload     TEXT,
    result      TEXT,
    updated_at  TEXT NOT NULL
);

-- Retried agent tool calls must not duplicate writes.
CREATE TABLE IF NOT EXISTS idempotency (
    key         TEXT PRIMARY KEY,
    command     TEXT NOT NULL,
    result      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_session  ON session_events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_node     ON session_events(session_id, node_key);
CREATE INDEX IF NOT EXISTS idx_nodes_goal      ON plan_nodes(goal_id);
CREATE INDEX IF NOT EXISTS idx_deps_goal       ON plan_dependencies(goal_id);
CREATE INDEX IF NOT EXISTS idx_props_learner   ON propositions(learner_id, status);
CREATE INDEX IF NOT EXISTS idx_mastery_learner ON mastery_evidence(learner_id);
CREATE INDEX IF NOT EXISTS idx_review_due      ON review_items(learner_id, due_at);
