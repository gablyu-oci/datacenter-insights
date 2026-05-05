-- Enable pgvector extension. Idempotent.
-- Required for skill_reference embeddings (text-embedding-3-large, dim=3072).
CREATE EXTENSION IF NOT EXISTS vector;
