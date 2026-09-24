"""真实 PostgreSQL 测试隔离：每个用例创建随机临时库，绝不清空业务库。"""
import os
from uuid import uuid4
import psycopg
from psycopg import sql
import pytest
from app.database import database_url as parse_url, checkpoint_conninfo
from scripts.init_db import initialize


@pytest.fixture
def database_url():
    value = os.getenv('TEST_DATABASE_URL')
    if not value:
        pytest.skip('需要 TEST_DATABASE_URL 指向具有 CREATEDB 权限的本地测试服务器')
    base = parse_url(value)
    name = 'fp_test_' + uuid4().hex
    admin = checkpoint_conninfo(base.render_as_string(hide_password=False))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    target = base.set(database=name).render_as_string(hide_password=False)
    try:
        initialize(target)
        yield target
    finally:
        # 仅删除本 fixture 创建且名字匹配的临时数据库；不使用用户传入的库名。
        assert name.startswith('fp_test_') and len(name) == 40
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
