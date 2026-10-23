"""Frozen independent local clip history; explicit maintenance migration only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0012_local_clips'
down_revision = '0011_editing'
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    _frozen_tables(metadata)['local_clips'].create(op.get_bind())
    op.execute("""
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_local_clips
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE FUNCTION fp_check_local_clip() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM fp_storyboard_versions WHERE id=NEW.storyboard_version_id
        AND project_id=NEW.project_id AND breakdown_version_id=NEW.storyboard_id AND version_no=NEW.version_no) THEN
        RAISE EXCEPTION 'local clip storyboard ownership or version mismatch';
      END IF;
      IF (SELECT count(*) FROM fp_local_clips WHERE project_id=NEW.project_id) >= 100 THEN
        RAISE EXCEPTION 'local clip project limit exceeded';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER local_clip_valid BEFORE INSERT ON fp_local_clips
      FOR EACH ROW EXECUTE FUNCTION fp_check_local_clip();
    """)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_local_clips)')).scalar():
        raise RuntimeError('Local clip history is not empty; forward migration required.')
    op.drop_table('fp_local_clips')
    op.execute('DROP FUNCTION fp_check_local_clip()')


def _frozen_tables(metadata):
    table = sa.Table('fp_local_clips', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('storyboard_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('version_no', sa.Integer, nullable=False),
        sa.Column('filename', sa.String(180), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('output', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_local_clip_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_local_clip_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_id'], ['fp_breakdown_versions.project_id', 'fp_breakdown_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.CheckConstraint("id ~ '^local_[a-f0-9]{32}$'", name='ck_local_clip_id'),
        sa.CheckConstraint('version_no >= 1', name='ck_local_clip_version'),
        sa.CheckConstraint('length(filename) BETWEEN 1 AND 180', name='ck_local_clip_filename'),
        sa.CheckConstraint("idempotency_key ~ '^[A-Za-z0-9_-]{16,64}$' AND request_sha256 ~ '^[a-f0-9]{64}$'", name='ck_local_clip_request'),
        sa.CheckConstraint("jsonb_typeof(output) = 'object' AND output->>'mime_type' IN ('video/mp4','video/webm') "
            "AND (output->>'size_bytes')::bigint BETWEEN 1 AND 268435456 "
            "AND (output->'metadata'->>'duration_ms')::integer BETWEEN 1 AND 600000", name='ck_local_clip_output'))
    sa.Index('ix_local_clip_series', table.c.project_id, table.c.storyboard_id, table.c.created_at)
    return {'local_clips': table}
