"""模型配置版本与分镜确认，冻结DDL，不导入运行时模型。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_production_foundation'
down_revision = '0004_story_game'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fp_model_profiles',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('current_version', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('current_version > 0', name='ck_model_profile_current'))
    op.create_table('fp_model_profile_versions',
        sa.Column('profile_id', sa.String(64), sa.ForeignKey('fp_model_profiles.id'), primary_key=True),
        sa.Column('version_no', sa.Integer, primary_key=True),
        sa.Column('config', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('version_no > 0', name='ck_model_profile_version'))
    op.create_table('fp_storyboard_confirmations',
        sa.Column('storyboard_version_id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64), nullable=False),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id', 'storyboard_version_id'],
                                ['fp_storyboard_versions.project_id', 'fp_storyboard_versions.id']))
    for table in ('fp_model_profile_versions', 'fp_storyboard_confirmations'):
        op.execute(f'CREATE TRIGGER production_history_immutable BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION fp_reject_history_change()')


def downgrade():
    connection = op.get_bind()
    for table in ('fp_model_profiles', 'fp_model_profile_versions', 'fp_storyboard_confirmations'):
        if connection.execute(sa.text(f'SELECT EXISTS(SELECT 1 FROM {table})')).scalar():
            raise RuntimeError('制作配置或确认记录非空，拒绝删除。请保留备份并采用前向迁移。')
    op.drop_table('fp_storyboard_confirmations')
    op.drop_table('fp_model_profile_versions')
    op.drop_table('fp_model_profiles')
