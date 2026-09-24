"""PostgreSQL 集成验收：事务配额与重启恢复必须使用真实数据库验证。"""
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.domain import CreateProject
from app.service import StoryService
from app.storage import Repository, BudgetExceeded
from tests.test_story import FakeModel, STORY, resume


def test_postgres_budget_is_atomic_across_connections(database_url):
    with StoryService(database_url, FakeModel(), max_calls=3) as service:
        project = service.create(CreateProject(story=STORY, mode='direct'))
        def reserve(_):
            repo = Repository(database_url)
            try:
                return repo.reserve_call(project['id'], 'test')
            except BudgetExceeded:
                return None
            finally:
                repo.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(reserve, range(12)))
        assert len([value for value in ids if value is not None]) == 3
        assert service.get(project['id'])['calls_used'] == 3


def test_postgres_restart_preserves_interrupt_and_budget(database_url):
    with StoryService(database_url, FakeModel()) as service:
        project = service.create(CreateProject(story=STORY))
    with StoryService(database_url, FakeModel()) as service:
        restored = service.get(project['id'])
        assert restored['interrupt'] == project['interrupt']
        assert restored['calls_used'] == 2
        assert resume(service, restored)['state']['status'] == 'confirmed'


def test_runtime_rejects_sqlite():
    with pytest.raises(ValueError, match='PostgreSQL'):
        Repository('sqlite:///stories.sqlite3')
