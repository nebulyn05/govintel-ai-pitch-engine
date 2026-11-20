from pathlib import Path


def test_schema_uses_idempotent_table_and_column_migrations():
    schema = (Path(__file__).parents[1] / "db" / "schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS" in schema
    assert "ADD COLUMN IF NOT EXISTS" in schema
    assert "CREATE INDEX IF NOT EXISTS" in schema
    assert "pitch_drafts_review_queue_idx" in schema
    assert "opportunities_priority_review_idx" in schema
