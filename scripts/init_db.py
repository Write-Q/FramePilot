"""显式升级业务表和图检查点表；应用启动不隐式修改表结构。"""
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver
from app.database import ROOT, database_url, checkpoint_conninfo


def initialize(url=None):
    value = database_url(url).render_as_string(hide_password=False)
    config = Config(str(ROOT / 'alembic.ini'))
    config.attributes['database_url'] = value
    command.upgrade(config, 'head')
    with PostgresSaver.from_conn_string(checkpoint_conninfo(value)) as saver:
        saver.setup()


if __name__ == '__main__':
    initialize()
    print('PostgreSQL 业务表和检查点表已就绪。')
