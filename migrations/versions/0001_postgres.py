"""建立 PostgreSQL 业务表。检查点表由 PostgresSaver.setup 单独管理。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_postgres'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fp_projects',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('snapshot', postgresql.JSONB(), nullable=False),
        sa.Column('max_calls', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('max_calls > 0', name='ck_fp_projects_budget'))
    op.create_table('fp_versions',
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), primary_key=True),
        sa.Column('version', sa.Integer(), primary_key=True),
        sa.Column('draft', sa.Text(), nullable=False),
        sa.Column('card', postgresql.JSONB(), nullable=False),
        sa.CheckConstraint('version >= 1', name='ck_fp_versions_positive'))
    op.create_table('fp_calls',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.String(64), sa.ForeignKey('fp_projects.id'), nullable=False),
        sa.Column('task', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('usage', postgresql.JSONB(), nullable=False))
    op.create_index('ix_fp_calls_project_id_id', 'fp_calls', ['project_id', 'id'])


def downgrade():
    op.drop_table('fp_calls')
    op.drop_table('fp_versions')
    op.drop_table('fp_projects')
