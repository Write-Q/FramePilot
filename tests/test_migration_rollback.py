"""导入中途失败不能留下半套业务数据。"""
import sqlite3
import psycopg
import pytest
from app.service import StoryService
from scripts.migrate_sqlite import migrate
from tests.test_sqlite_migration import legacy_fixture
from tests.test_story import FakeModel


def test_import_constraint_failure_rolls_back_all_rows(database_url, tmp_path):
    source = tmp_path / 'legacy'
    legacy_fixture(source)
    with sqlite3.connect(source / 'stories.sqlite3') as conn:
        conn.execute('INSERT INTO versions SELECT * FROM versions')
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrate(source, database_url)
    with StoryService(database_url, FakeModel()) as service:
        with pytest.raises(KeyError):
            service.get('legacy_project')
    with sqlite3.connect(source / 'stories.sqlite3') as conn:
        conn.execute('DELETE FROM versions WHERE rowid = (SELECT MAX(rowid) FROM versions)')
    assert migrate(source, database_url)['projects'] == 1
