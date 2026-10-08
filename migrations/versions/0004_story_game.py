"""独立游戏快照，领域媒体桥接留给正式剧本导出阶段。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0004_story_game'
down_revision='0003_legacy_domain_backfill'
branch_labels=None
depends_on=None


def upgrade():
    """添加游戏存档，不修改旧项目及32张领域表。"""
    op.create_table('fp_game_sessions',sa.Column('id',sa.String(64),primary_key=True),
                    sa.Column('revision',sa.Integer,nullable=False),sa.Column('snapshot',JSONB,nullable=False),
                    sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
                    sa.CheckConstraint('revision > 0',name='ck_game_revision'))


def downgrade():
    """拒绝删除已有游戏存档。"""
    if op.get_bind().execute(sa.text('SELECT EXISTS(SELECT 1 FROM fp_game_sessions)')).scalar():
        raise RuntimeError('游戏存档非空，拒绝删除。请保留备份并采用前向迁移。')
    op.drop_table('fp_game_sessions')
