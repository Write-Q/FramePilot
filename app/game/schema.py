"""将独立游戏表纳入Alembic元信息，避免后续自动迁移误删。"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


def register_game(metadata):
    """与0004迁移一致的游戏存档表定义。"""
    return sa.Table('fp_game_sessions',metadata,
                    sa.Column('id',sa.String(64),primary_key=True),sa.Column('revision',sa.Integer,nullable=False),
                    sa.Column('snapshot',JSONB,nullable=False),
                    sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
                    sa.CheckConstraint('revision > 0',name='ck_game_revision'))
