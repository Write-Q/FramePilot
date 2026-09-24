"""旧数据导入验收：保留人工暂停、原稿、版本和调用额度，失败整批回滚。"""
import json
import sqlite3
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from app.domain import CreateProject
from app.service import StoryService
from app.workflow import build_graph
from tests.test_story import FakeModel, STORY, resume


def legacy_fixture(path):
    # 用旧表结构与真实 SQLite 检查点构造一个暂停项目，不调用外部模型。
    path.mkdir()
    conn = sqlite3.connect(path / 'stories.sqlite3')
    conn.executescript('''
      CREATE TABLE projects(id TEXT PRIMARY KEY,snapshot TEXT,max_calls INTEGER,created_at TEXT);
      CREATE TABLE versions(project_id TEXT,version INTEGER,draft TEXT,card TEXT);
      CREATE TABLE calls(id INTEGER PRIMARY KEY,project_id TEXT,task TEXT,status TEXT,usage TEXT);
    ''')
    class LegacyRepo:
        def reserve_call(self, project_id, task):
            cur = conn.execute('INSERT INTO calls(project_id,task,status,usage) VALUES (?,?,?,?)',
                               (project_id, task, 'started', '{}'))
            conn.commit()
            return cur.lastrowid
        def finish_call(self, call_id, status, usage=None):
            conn.execute('UPDATE calls SET status=?,usage=? WHERE id=?',
                         (status, json.dumps(usage or {}), call_id))
            conn.commit()
        def version(self, state):
            conn.execute('INSERT INTO versions VALUES (?,?,?,?)',
                         (state['project_id'],state['version'],state['draft'],json.dumps(state['card'])))
            conn.commit()
    state = dict(project_id='legacy_project', original_story=STORY, draft=STORY,
                 mode='collaborative', constraints='', version=1, reviewed_version=0,
                 revision_count=0, card={}, issues=[], review_history=[], feedback_history=[],
                 accepted_issue_ids=[], status='running', stop_reason='', error='')
    with SqliteSaver.from_conn_string(str(path / 'checkpoints.sqlite3')) as saver:
        graph = build_graph(FakeModel(), LegacyRepo(), saver)
        config = StoryService.config(state['project_id'])
        graph.invoke(state, config)
        snapshot = graph.get_state(config)
        item = snapshot.tasks[0].interrupts[0]
        pending = {'id':item.id, **item.value}
        conn.execute('INSERT INTO projects VALUES (?,?,?,?)',
                     (state['project_id'],json.dumps({'state':dict(snapshot.values),'interrupt':pending}),10,
                      '2026-09-01T00:00:00+00:00'))
        conn.commit()
    conn.close()
    return pending


def test_import_preserves_resume_and_refuses_nonempty_target(database_url, tmp_path):
    from scripts.migrate_sqlite import migrate
    source = tmp_path / 'legacy'
    pending = legacy_fixture(source)
    report = migrate(source, database_url)
    assert report['projects'] == 1
    with StoryService(database_url, FakeModel()) as service:
        project = service.get('legacy_project')
        assert project['interrupt'] == pending
        assert project['calls_used'] == 2
        assert project['state']['original_story'] == STORY
        assert len(service.versions(project['id'])) == 1
        assert resume(service, project)['state']['status'] == 'confirmed'
    with pytest.raises(ValueError, match='非空'):
        migrate(source, database_url)


def test_missing_checkpoints_abort_without_partial_import(database_url, tmp_path):
    from scripts.migrate_sqlite import migrate
    source = tmp_path / 'legacy'
    legacy_fixture(source)
    # 删除的是测试 fixture 的图数据，用于模拟不完整备份。
    with sqlite3.connect(source / 'checkpoints.sqlite3') as conn:
        conn.execute('DELETE FROM checkpoints')
    with pytest.raises(ValueError, match='检查点'):
        migrate(source, database_url)
    with StoryService(database_url, FakeModel()) as service:
        with pytest.raises(KeyError):
            service.get('legacy_project')
