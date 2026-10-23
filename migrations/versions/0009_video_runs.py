"""Video runtime frozen schema; no automatic business database migration."""
from alembic import op
revision = '0009_video_runs'
down_revision = '0008_shot_media'
branch_labels = None
depends_on = None
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def _frozen_tables(metadata):
    runs = sa.Table('fp_video_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('shot_id', sa.String(64), nullable=False),
        sa.Column('shot_key', sa.String(64), nullable=False),
        sa.Column('first_frame_run_id', sa.String(64), nullable=False),
        sa.Column('first_frame_media_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('external_id', sa.String(1000)),
        sa.Column('claim_id', sa.String(64)),
        sa.Column('error_code', sa.String(64)),
        sa.Column('output', JSONB(none_as_null=True)),
        sa.Column('next_poll_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'id', name='uq_video_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_video_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'shot_id'], ['fp_shots.project_id', 'fp_shots.id']),
        sa.ForeignKeyConstraint(['project_id', 'first_frame_run_id'], ['fp_shot_media_runs.project_id', 'fp_shot_media_runs.id']),
        sa.ForeignKeyConstraint(['project_id', 'first_frame_media_id'], ['fp_media_files.project_id', 'fp_media_files.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('queued','submitting','submitted','polling','succeeded','failed','unknown','cancelled')", name='ck_video_status'),
        sa.CheckConstraint("(status IN ('queued','submitting','submitted','polling')) = (finished_at IS NULL)", name='ck_video_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (output IS NOT NULL)", name='ck_video_output'),
        sa.CheckConstraint("status NOT IN ('submitted','polling','succeeded') OR external_id IS NOT NULL", name='ck_video_external'),
        sa.CheckConstraint("(status IN ('submitting','polling')) = (claim_id IS NOT NULL)", name='ck_video_claim'),
        sa.CheckConstraint("(status = 'submitted') = (next_poll_at IS NOT NULL)", name='ck_video_poll_due'))
    sa.Index('ix_video_queue', runs.c.status, runs.c.next_poll_at, runs.c.created_at)
    sa.Index('uq_video_active_shot', runs.c.project_id, runs.c.storyboard_version_id, runs.c.shot_key,
             unique=True, postgresql_where=runs.c.status.in_(['queued', 'submitting', 'submitted', 'polling']))
    selections = sa.Table('fp_video_selections', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_video_runs.project_id', 'fp_video_runs.id']))
    sa.Index('ix_video_selections_project', selections.c.project_id, selections.c.id)
    return {'video_runs': runs, 'video_selections': selections}


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(bind=op.get_bind())
    tables = _frozen_tables(metadata)
    tables['video_runs'].create(op.get_bind())
    tables['video_selections'].create(op.get_bind())
    op.execute("""
    CREATE FUNCTION fp_guard_video_run() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'video history is immutable'; END IF;
      IF OLD.status NOT IN ('queued','submitting','submitted','polling') OR
         (to_jsonb(NEW) - ARRAY['status','error_code','external_id','claim_id','output','started_at','finished_at','next_poll_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','error_code','external_id','claim_id','output','started_at','finished_at','next_poll_at']) THEN
        RAISE EXCEPTION 'video input or terminal history is immutable';
      END IF;
      IF NOT ((OLD.status='queued' AND NEW.status IN ('submitting','cancelled')) OR
              (OLD.status='submitting' AND NEW.status IN ('submitted','failed','unknown')) OR
              (OLD.status='submitted' AND NEW.status IN ('polling','unknown')) OR
              (OLD.status='polling' AND NEW.status IN ('submitted','succeeded','failed','unknown'))) THEN
        RAISE EXCEPTION 'invalid video transition';
      END IF;
      IF NEW.external_id IS DISTINCT FROM OLD.external_id AND NOT
         (OLD.status='submitting' AND NEW.status='submitted' AND OLD.external_id IS NULL AND NEW.external_id IS NOT NULL) THEN
        RAISE EXCEPTION 'external video identity is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER video_run_guard BEFORE UPDATE OR DELETE ON fp_video_runs
      FOR EACH ROW EXECUTE FUNCTION fp_guard_video_run();
    CREATE FUNCTION fp_check_video_owner() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status <> 'queued' OR NEW.external_id IS NOT NULL OR NOT EXISTS
        (SELECT 1 FROM fp_shots WHERE id=NEW.shot_id AND project_id=NEW.project_id
         AND storyboard_version_id=NEW.storyboard_version_id AND content->>'key'=NEW.shot_key) THEN
        RAISE EXCEPTION 'video shot input mismatch';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM fp_shot_media_runs WHERE id=NEW.first_frame_run_id
        AND project_id=NEW.project_id AND storyboard_version_id=NEW.storyboard_version_id
        AND shot_key=NEW.shot_key AND frame_role='first' AND status='succeeded'
        AND media_id=NEW.first_frame_media_id) THEN
        RAISE EXCEPTION 'video first frame mismatch';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER video_owner BEFORE INSERT ON fp_video_runs
      FOR EACH ROW EXECUTE FUNCTION fp_check_video_owner();
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_video_selections
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE FUNCTION fp_check_video_selection() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM fp_video_runs WHERE id=NEW.run_id
        AND project_id=NEW.project_id AND status='succeeded') THEN
        RAISE EXCEPTION 'only successful videos can be selected';
      END IF;
      NEW.id := nextval(pg_get_serial_sequence('fp_video_selections','id'));
      RETURN NEW;
    END $$;
    CREATE TRIGGER video_selection_valid BEFORE INSERT ON fp_video_selections
      FOR EACH ROW EXECUTE FUNCTION fp_check_video_selection();
    """)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_video_runs)')).scalar():
        raise RuntimeError('Video history is not empty; forward migration required.')
    op.drop_table('fp_video_selections')
    op.drop_table('fp_video_runs')
    op.execute('DROP FUNCTION fp_guard_video_run()')
    op.execute('DROP FUNCTION fp_check_video_owner()')
    op.execute('DROP FUNCTION fp_check_video_selection()')
