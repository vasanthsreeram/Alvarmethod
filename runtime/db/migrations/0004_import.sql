-- Alvarmethod runtime schema, migration 4: document ingestion.
-- Chunks carry where they came from: a page for PDFs, byte offsets for text
-- (into the file for .md/.txt, into the page's extracted text for PDFs). Additive only.

ALTER TABLE resources ADD COLUMN bytes INTEGER;
ALTER TABLE resources ADD COLUMN pages INTEGER;
ALTER TABLE resources ADD COLUMN stored_path TEXT;            -- copy under <data>/resources/

ALTER TABLE resource_chunks ADD COLUMN start_offset INTEGER;
ALTER TABLE resource_chunks ADD COLUMN end_offset INTEGER;

CREATE INDEX IF NOT EXISTS idx_resources_sha ON resources(learner_id, sha256);
