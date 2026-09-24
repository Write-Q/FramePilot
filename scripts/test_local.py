"""在本机 PostgreSQL 的随机临时库中测试，不调用真实模型。"""
import os
import pytest
from app.database import database_url, ROOT
from dotenv import load_dotenv


if __name__ == '__main__':
    load_dotenv(ROOT / '.env', override=False)
    value = os.getenv('TEST_DATABASE_URL')
    if not value:
        url = database_url()
        if url.host not in ('localhost', '127.0.0.1', '::1'):
            raise SystemExit('非本机数据库请显式设置 TEST_DATABASE_URL。')
        os.environ['TEST_DATABASE_URL'] = url.render_as_string(hide_password=False)
    raise SystemExit(pytest.main(['-q', '-p', 'no:cacheprovider', '--tb=short']))
