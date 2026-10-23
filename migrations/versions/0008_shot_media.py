"""Shot image queue and append-only selections, frozen schema."""
from alembic import op
revision = '0008_shot_media'
down_revision = '0007_storyboard_reviews'
branch_labels = None
depends_on = None
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def _frozen_tables(metadata):
    runs = sa.Table('fp_shot_media_runs', metadata,
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('shot_id', sa.String(64), nullable=False),
        sa.Column('shot_key', sa.String(64), nullable=False),
        sa.Column('frame_role', sa.String(16), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('media_id', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'id', name='uq_shot_media_owned'),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_shot_media_request'),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'shot_id'], ['fp_shots.project_id', 'fp_shots.id']),
        sa.ForeignKeyConstraint(['project_id', 'media_id'], ['fp_media_files.project_id', 'fp_media_files.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("kind = 'image'", name='ck_shot_media_kind'),
        sa.CheckConstraint("frame_role IN ('first','key','last')", name='ck_shot_media_role'),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','unknown','cancelled')", name='ck_shot_media_status'),
        sa.CheckConstraint("(status IN ('queued','running')) = (finished_at IS NULL)", name='ck_shot_media_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (media_id IS NOT NULL)", name='ck_shot_media_result'))
    sa.Index('ix_shot_media_queue', runs.c.status, runs.c.created_at)
    selections = sa.Table('fp_shot_media_selections', metadata,
        sa.Column('id', sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'run_id'], ['fp_shot_media_runs.project_id', 'fp_shot_media_runs.id']))
    sa.Index('ix_shot_media_selections_project', selections.c.project_id, selections.c.id)
    return {'media_runs': runs, 'media_selections': selections}


def upgrade():
    metadata = sa.MetaData()
    # Resolve existing foreign-key targets; this does not recreate them.
    metadata.reflect(bind=op.get_bind())
    tables = _frozen_tables(metadata)
    tables['media_runs'].create(op.get_bind())
    tables['media_selections'].create(op.get_bind())
    op.execute("""
    CREATE FUNCTION fp_guard_shot_media() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'media history is immutable'; END IF;
      IF OLD.status NOT IN ('queued','running') OR
         (to_jsonb(NEW) - ARRAY['status','error_code','media_id','started_at','finished_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','error_code','media_id','started_at','finished_at']) THEN
        RAISE EXCEPTION 'media input or terminal history is immutable';
      END IF;
      IF NOT ((OLD.status = 'queued' AND NEW.status IN ('running','cancelled')) OR
              (OLD.status = 'running' AND NEW.status IN ('succeeded','failed','unknown'))) THEN
        RAISE EXCEPTION 'invalid media transition';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER shot_media_guard BEFORE UPDATE OR DELETE ON fp_shot_media_runs
      FOR EACH ROW EXECUTE FUNCTION fp_guard_shot_media();
    CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON fp_shot_media_selections
      FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change();
    CREATE FUNCTION fp_check_shot_media_owner() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM fp_shots WHERE id=NEW.shot_id AND project_id=NEW.project_id
        AND storyboard_version_id=NEW.storyboard_version_id AND content->>'key'=NEW.shot_key) THEN
        RAISE EXCEPTION 'media shot version mismatch';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER shot_media_owner BEFORE INSERT ON fp_shot_media_runs
      FOR EACH ROW EXECUTE FUNCTION fp_check_shot_media_owner();
    CREATE FUNCTION fp_check_media_selection() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM id FROM fp_projects WHERE id=NEW.project_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM fp_shot_media_runs WHERE id=NEW.run_id
        AND project_id=NEW.project_id AND status='succeeded') THEN
        RAISE EXCEPTION 'only successful media can be selected';
      END IF;
      NEW.id := nextval(pg_get_serial_sequence('fp_shot_media_selections','id'));
      RETURN NEW;
    END $$;
    CREATE TRIGGER media_selection_valid BEFORE INSERT ON fp_shot_media_selections
      FOR EACH ROW EXECUTE FUNCTION fp_check_media_selection();
    """)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_shot_media_runs)')).scalar():
        raise RuntimeError('Media history is not empty; forward migration required.')
    op.drop_table('fp_shot_media_selections')
    op.drop_table('fp_shot_media_runs')
    op.execute('DROP FUNCTION fp_guard_shot_media()')
    op.execute('DROP FUNCTION fp_check_shot_media_owner()')
    op.execute('DROP FUNCTION fp_check_media_selection()')
