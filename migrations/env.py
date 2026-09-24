"""从环境读取连接；Alembic 只管理 fp_ 业务表，不触碰 LangGraph 的表。"""
from alembic import context
from sqlalchemy import create_engine, pool
from app.database import database_url
from app.models import Base


def include_name(name, type_, parent_names):
    # 自动生成迁移时忽略检查点表，否则会错误建议删除第三方组件的表。
    return type_ != 'table' or name.startswith('fp_')


config = context.config
url = database_url(config.attributes.get('database_url'))
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True,
                      include_name=include_name)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata,
                              include_name=include_name)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
