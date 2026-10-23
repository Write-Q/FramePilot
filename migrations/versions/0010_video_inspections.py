"""Frozen video inspection history schema; explicitly applied by maintenance only."""
from alembic import op
revision = '0010_video_inspections'
down_revision = '0009_video_runs'
branch_labels = None
depends_on = None
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def _frozen_tables(metadata):
    reports = sa.Table('fp_video_inspections', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('video_checksum', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('technical', JSONB, nullable=False),
        sa.Column('frames', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_video_inspection_owned'),
        sa.UniqueConstraint('project_id', 'run_id', 'id', name='uq_video_inspection_run_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_inspection_request'),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.CheckConstraint("jsonb_typeof(frames) = 'array' AND jsonb_array_length(frames) BETWEEN 1 AND 12", name='ck_video_inspection_frames'))
    sa.Index('ix_video_inspection_run', reports.c.project_id, reports.c.run_id, reports.c.created_at)
    notes = sa.Table('fp_video_inspection_notes', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('inspection_id', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('expected_version', sa.Integer, nullable=False),
        sa.Column('decision', sa.String(16), nullable=False),
        sa.Column('findings', JSONB, nullable=False),
        sa.Column('comment', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_inspection_note_request'),
        sa.ForeignKeyConstraint(['project_id', 'run_id', 'inspection_id'],
            ['fp_video_inspections.project_id', 'fp_video_inspections.run_id', 'fp_video_inspections.id']),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']),
        sa.CheckConstraint("decision IN ('reviewed','needs_revision')", name='ck_video_inspection_decision'),
        sa.CheckConstraint('expected_version >= 1', name='ck_video_inspection_note_version'),
        sa.CheckConstraint('length(comment) <= 2000', name='ck_video_inspection_comment'),
        sa.CheckConstraint("jsonb_typeof(findings) = 'array' AND jsonb_array_length(findings) <= 20", name='ck_video_inspection_findings'),
        sa.CheckConstraint("decision <> 'needs_revision' OR jsonb_array_length(findings) > 0", name='ck_video_inspection_revision'))
    sa.Index('ix_video_inspection_notes', notes.c.project_id, notes.c.inspection_id, notes.c.id)
    return {'video_inspections': reports, 'video_inspection_notes': notes}


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    tables = _frozen_tables(metadata)
    tables['video_inspections'].create(op.get_bind())
    tables['video_inspection_notes'].create(op.get_bind())
    op.execute("""
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_video_inspections
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_video_inspection_notes
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE FUNCTION fp_check_video_inspection() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM fp_video_runs WHERE id=NEW.run_id
        AND project_id=NEW.project_id AND status='succeeded'
        AND storyboard_version_id=NEW.storyboard_version_id
        AND output->>'checksum'=NEW.video_checksum) THEN
        RAISE EXCEPTION 'inspection video ownership or checksum mismatch';
      END IF;
      IF (SELECT count(*) FROM fp_video_inspections
          WHERE project_id=NEW.project_id AND run_id=NEW.run_id) >= 10 THEN
        RAISE EXCEPTION 'video inspection report limit exceeded';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER video_inspection_valid BEFORE INSERT ON fp_video_inspections
      FOR EACH ROW EXECUTE FUNCTION fp_check_video_inspection();
    CREATE FUNCTION fp_check_video_inspection_note() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE duration integer;
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      SELECT (technical->'actual'->>'duration_ms')::integer INTO duration FROM fp_video_inspections
        WHERE id=NEW.inspection_id AND project_id=NEW.project_id AND run_id=NEW.run_id
          AND (manifest->>'version')::integer=NEW.expected_version;
      IF duration IS NULL THEN RAISE EXCEPTION 'inspection note version mismatch'; END IF;
      IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.findings) AS f WHERE
        jsonb_typeof(f->'start_ms') IS DISTINCT FROM 'number' OR
        jsonb_typeof(f->'end_ms') IS DISTINCT FROM 'number' OR
        (f->>'start_ms')::integer < 0 OR (f->>'start_ms')::integer >= duration OR
        (f->>'end_ms')::integer < (f->>'start_ms')::integer OR (f->>'end_ms')::integer > duration OR
        f->>'severity' IS NULL OR f->>'severity' NOT IN ('low','medium','high') OR
        f->>'description' IS NULL OR length(btrim(f->>'description')) NOT BETWEEN 1 AND 2000) THEN
        RAISE EXCEPTION 'inspection finding outside actual duration or invalid';
      END IF;
      IF (SELECT count(*) FROM fp_video_inspection_notes
          WHERE project_id=NEW.project_id AND inspection_id=NEW.inspection_id) >= 50 THEN
        RAISE EXCEPTION 'inspection manual note limit exceeded';
      END IF;
      NEW.id := nextval(pg_get_serial_sequence('fp_video_inspection_notes','id'));
      RETURN NEW;
    END $$;
    CREATE TRIGGER video_inspection_note_valid BEFORE INSERT ON fp_video_inspection_notes
      FOR EACH ROW EXECUTE FUNCTION fp_check_video_inspection_note();
    """)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_video_inspections)')).scalar():
        raise RuntimeError('Video inspection history is not empty; forward migration required.')
    op.drop_table('fp_video_inspection_notes')
    op.drop_table('fp_video_inspections')
    op.execute('DROP FUNCTION fp_check_video_inspection_note()')
    op.execute('DROP FUNCTION fp_check_video_inspection()')
