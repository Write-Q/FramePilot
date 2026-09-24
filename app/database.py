"""数据库连接配置。运行时只支持 PostgreSQL，不静默退回本地 SQLite。"""
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parent.parent


def database_url(value=None):
    load_dotenv(ROOT / '.env', override=False)
    value = value or os.getenv('DATABASE_URL')
    if not isinstance(value, str) or not value:
        raise ValueError('请设置 DATABASE_URL，指向 PostgreSQL；参考 .env.example。')
    try:
        url = make_url(value)
        if url.drivername not in ('postgresql', 'postgresql+psycopg'):
            raise ValueError()
        return url.set(drivername='postgresql+psycopg')
    except Exception:
        raise ValueError('DATABASE_URL 必须是有效的 PostgreSQL 连接地址。') from None


def checkpoint_conninfo(value):
    """SQLAlchemy URL 转成 psycopg 参数，正确保留密码中的特殊字符。"""
    url = database_url(value)
    params = dict(url.query)
    for key, val in [('host', url.host), ('port', url.port), ('user', url.username),
                     ('password', url.password), ('dbname', url.database)]:
        if val is not None:
            params[key] = str(val)
    params.setdefault('connect_timeout', '10')
    return make_conninfo(**params)
