"""独立文字分镜审核记录；冻结 DDL，不自动迁移业务库。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007_storyboard_reviews'
down_revision = '0006_storyboard_runs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fp_storyboard_review_runs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('source_version_id', sa.String(64), nullable=False),
        sa.Column('storyboard_version_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('usage', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('report', JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_storyboard_review_request'),
        sa.ForeignKeyConstraint(['project_id', 'source_version_id'], ['fp_script_versions.project_id', 'fp_script_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('running','succeeded','failed','abandoned')", name='ck_storyboard_review_status'),
        sa.CheckConstraint("(status = 'running') = (finished_at IS NULL)", name='ck_storyboard_review_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (report IS NOT NULL)", name='ck_storyboard_review_result'))
    op.create_index('uq_storyboard_review_active', 'fp_storyboard_review_runs', ['project_id'], unique=True,
                    postgresql_where=sa.text("status = 'running'"))
    op.create_index('ix_storyboard_reviews_project_created', 'fp_storyboard_review_runs', ['project_id', 'created_at'])
    op.execute("""
    CREATE FUNCTION fp_guard_storyboard_review() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'storyboard review history is immutable';
      END IF;
      IF OLD.status <> 'running' OR
         (to_jsonb(NEW) - ARRAY['status','error_code','usage','report','finished_at']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','error_code','usage','report','finished_at']) THEN
        RAISE EXCEPTION 'storyboard review input or terminal history is immutable';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER fp_storyboard_review_guard BEFORE UPDATE OR DELETE ON fp_storyboard_review_runs
      FOR EACH ROW EXECUTE FUNCTION fp_guard_storyboard_review();
    """)


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_storyboard_review_runs)')).scalar():
        raise RuntimeError('审核记录非空，拒绝删除；请采用前向迁移并保留备份。')
    op.drop_table('fp_storyboard_review_runs')
    op.execute('DROP FUNCTION fp_guard_storyboard_review()')
