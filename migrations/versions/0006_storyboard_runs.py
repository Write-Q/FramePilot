"""可追溯的分镜规划运行，冻结 DDL；不复用指向剧本结果的任务字段。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006_storyboard_runs'
down_revision = '0005_production_foundation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fp_storyboard_runs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('source_version_id', sa.String(64), nullable=False),
        sa.Column('profile_id', sa.String(64), nullable=False),
        sa.Column('profile_version', sa.Integer, nullable=False),
        sa.Column('manifest', JSONB, nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('error_code', sa.String(64)),
        sa.Column('usage', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('storyboard_version_id', sa.String(64)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'idempotency_key', name='uq_storyboard_run_request'),
        sa.ForeignKeyConstraint(['project_id', 'source_version_id'], ['fp_script_versions.project_id', 'fp_script_versions.id']),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'], ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']),
        sa.ForeignKeyConstraint(['profile_id', 'profile_version'], ['fp_model_profile_versions.profile_id', 'fp_model_profile_versions.version_no']),
        sa.CheckConstraint("status IN ('running','succeeded','failed','abandoned')", name='ck_storyboard_run_status'),
        sa.CheckConstraint("(status = 'running') = (finished_at IS NULL)", name='ck_storyboard_run_finished'),
        sa.CheckConstraint("(status = 'succeeded') = (storyboard_version_id IS NOT NULL)", name='ck_storyboard_run_result'))
    op.create_index('uq_storyboard_run_active', 'fp_storyboard_runs', ['project_id'], unique=True,
                    postgresql_where=sa.text("status = 'running'"))
    op.create_index('ix_storyboard_runs_project_created', 'fp_storyboard_runs', ['project_id', 'created_at'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_storyboard_runs)')).scalar():
        raise RuntimeError('分镜运行记录非空，拒绝删除；请采用前向迁移并保留备份。')
    op.drop_table('fp_storyboard_runs')
