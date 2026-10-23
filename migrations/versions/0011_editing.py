"""Immutable postproduction history and export state machine; maintenance only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0011_editing'
down_revision = '0010_video_inspections'
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    tables = _frozen_tables(metadata)
    for table in tables.values():
        table.create(op.get_bind())
    op.execute("""
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_editing_timelines
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_editing_audio
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_editing_acceptances
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE FUNCTION fp_guard_editing_export() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'export history is immutable'; END IF;
      IF OLD.status NOT IN ('queued','running') OR
        (to_jsonb(NEW) - ARRAY['status','claim_id','error_code','output','started_at','finished_at']) IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['status','claim_id','error_code','output','started_at','finished_at']) THEN
        RAISE EXCEPTION 'export inputs or terminal history are immutable';
      END IF;
      IF NOT ((OLD.status='queued' AND NEW.status IN ('running','unknown')) OR
              (OLD.status='running' AND NEW.status IN ('succeeded','failed','unknown'))) THEN
        RAISE EXCEPTION 'invalid export transition';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER editing_export_guard BEFORE UPDATE OR DELETE ON fp_editing_exports
      FOR EACH ROW EXECUTE FUNCTION fp_guard_editing_export();
    CREATE FUNCTION fp_check_editing_timeline() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM fp_storyboard_versions WHERE id=NEW.storyboard_version_id
        AND project_id=NEW.project_id AND breakdown_version_id=NEW.storyboard_id AND version_no=NEW.source_version) THEN
        RAISE EXCEPTION 'timeline storyboard ownership or version mismatch';
      END IF;
      IF NEW.version_no <> COALESCE((SELECT max(version_no) FROM fp_editing_timelines
        WHERE project_id=NEW.project_id AND storyboard_id=NEW.storyboard_id),0)+1 THEN
        RAISE EXCEPTION 'timeline version must be sequential';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER editing_timeline_valid BEFORE INSERT ON fp_editing_timelines
      FOR EACH ROW EXECUTE FUNCTION fp_check_editing_timeline();
    CREATE FUNCTION fp_check_editing_export() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status <> 'queued' OR NOT EXISTS (SELECT 1 FROM fp_editing_timelines
        WHERE id=NEW.timeline_id AND project_id=NEW.project_id AND storyboard_id=NEW.storyboard_id
        AND version_no=(NEW.manifest->>'timeline_version')::integer) THEN
        RAISE EXCEPTION 'export timeline ownership or initial state mismatch';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER editing_export_valid BEFORE INSERT ON fp_editing_exports
      FOR EACH ROW EXECUTE FUNCTION fp_check_editing_export();
    CREATE FUNCTION fp_check_editing_acceptance() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM fp_editing_exports WHERE id=NEW.export_id
        AND project_id=NEW.project_id AND status='succeeded') THEN
        RAISE EXCEPTION 'only succeeded exports can be accepted';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER editing_acceptance_valid BEFORE INSERT ON fp_editing_acceptances
      FOR EACH ROW EXECUTE FUNCTION fp_check_editing_acceptance();
    """)


def downgrade():
    for name in ('fp_editing_timelines', 'fp_editing_audio', 'fp_editing_exports', 'fp_editing_acceptances'):
        if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM ' + name + ')')).scalar():
            raise RuntimeError('Postproduction history is not empty; forward migration required.')
    for name in ('fp_editing_acceptances', 'fp_editing_exports', 'fp_editing_audio', 'fp_editing_timelines'):
        op.drop_table(name)
    for name in ('fp_check_editing_acceptance', 'fp_check_editing_export', 'fp_check_editing_timeline', 'fp_guard_editing_export'):
        op.execute('DROP FUNCTION ' + name + '()')


def _frozen_tables(metadata):
    timelines = sa.Table('fp_editing_timelines', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('storyboard_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('version_no', sa.Integer, nullable=False),
        sa.Column('source_version', sa.Integer, nullable=False),
        sa.Column('content', JSONB, nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_editing_timeline_owned'),
        sa.UniqueConstraint('project_id', 'storyboard_id', 'version_no', name='uq_editing_timeline_version'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_id'], ['fp_breakdown_versions.project_id', 'fp_breakdown_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.CheckConstraint('version_no >= 1 AND source_version >= 1', name='ck_editing_timeline_version'))
    audio = sa.Table('fp_editing_audio', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('storyboard_id', sa.String(64), nullable=False),
        sa.Column('output', JSONB, nullable=False),
        sa.Column('duration_ms', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'id', name='uq_editing_audio_owned'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_id'], ['fp_breakdown_versions.project_id', 'fp_breakdown_versions.id']),
        sa.CheckConstraint('duration_ms BETWEEN 1 AND 600000', name='ck_editing_audio_duration'))
    exports = sa.Table('fp_editing_exports', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('storyboard_id', sa.String(64), nullable=False),
        sa.Column('timeline_id', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('claim_id', sa.String(64)),
        sa.Column('error_code', sa.String(64)),
        sa.Column('output', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'id', name='uq_editing_export_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_editing_export_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_id'], ['fp_breakdown_versions.project_id', 'fp_breakdown_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'timeline_id'], ['fp_editing_timelines.project_id', 'fp_editing_timelines.id']),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','unknown')", name='ck_editing_export_status'),
        sa.CheckConstraint("(status IN ('queued','running')) = (finished_at IS NULL)", name='ck_editing_export_finished'),
        sa.CheckConstraint("(status = 'running') = (claim_id IS NOT NULL)", name='ck_editing_export_claim'),
        sa.CheckConstraint("(status = 'succeeded') = (output IS NOT NULL)", name='ck_editing_export_output'))
    sa.Index('ix_editing_export_queue', exports.c.status, exports.c.created_at)
    accepts = sa.Table('fp_editing_acceptances', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('export_id', sa.String(64), nullable=False),
        sa.Column('comment', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('project_id', 'export_id', name='uq_editing_acceptance_export'),
        sa.ForeignKeyConstraint(['project_id', 'export_id'], ['fp_editing_exports.project_id', 'fp_editing_exports.id']),
        sa.CheckConstraint('length(comment) <= 2000', name='ck_editing_acceptance_comment'))
    return {'editing_timelines': timelines, 'editing_audio': audio, 'editing_exports': exports,
            'editing_acceptances': accepts}
