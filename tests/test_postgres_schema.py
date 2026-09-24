"""业务迁移不得把 LangGraph 自己管理的表识别成待删除对象。"""
from alembic import command
from alembic.config import Config
from app.database import ROOT
from scripts.init_db import initialize


def test_schema_check_preserves_graph_tables_and_setup_is_repeatable(database_url):
    initialize(database_url)
    config = Config(str(ROOT / 'alembic.ini'))
    config.attributes['database_url'] = database_url
    command.check(config)
