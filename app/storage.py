"""业务存储与调用账本。它与 LangGraph 检查点职责不同。"""
import json
import sqlite3
from datetime import datetime, timezone
from threading import RLock


class BudgetExceeded(RuntimeError):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class Repository:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = RLock()
        self.conn.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, max_calls INTEGER NOT NULL,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (
              project_id TEXT NOT NULL, version INTEGER NOT NULL, draft TEXT NOT NULL,
              card TEXT NOT NULL, PRIMARY KEY(project_id, version));
            CREATE TABLE IF NOT EXISTS calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
              task TEXT NOT NULL, status TEXT NOT NULL, usage TEXT NOT NULL DEFAULT '{}');
        ''')

    # 创建项目记录，snapshot 同时保存业务状态及人工暂停信息。
    def create(self, project_id, state, max_calls):
        with self.lock, self.conn:
            self.conn.execute('INSERT INTO projects VALUES (?,?,?,?)',
                              (project_id, dump({'state': state, 'interrupt': None}), max_calls,
                               datetime.now(timezone.utc).isoformat()))

    # 更新当前项目快照，不覆盖历史正文版本。
    def save(self, project_id, state, pending):
        with self.lock, self.conn:
            self.conn.execute('UPDATE projects SET snapshot=? WHERE id=?',
                              (dump({'state': state, 'interrupt': pending}), project_id))

    # 按项目编号和版本号保存正文及卡片；同一版本不重复插入。
    def version(self, state):
        with self.lock, self.conn:
            self.conn.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?,?)',
                              (state['project_id'], state['version'], state['draft'], dump(state['card'])))

    # 读取项目快照与调用账本；calls_used 包含失败调用。
    def get(self, project_id):
        with self.lock:
            row = self.conn.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            snapshot = json.loads(row['snapshot'])
            calls = self.conn.execute('SELECT task,status,usage FROM calls WHERE project_id=? ORDER BY id', (project_id,)).fetchall()
            return {'id': project_id, **snapshot, 'created_at': row['created_at'],
                    'max_calls': row['max_calls'], 'calls_used': len(calls),
                    'calls': [{'task': c['task'], 'status': c['status'], 'usage': json.loads(c['usage'])} for c in calls]}

    # 按版本号顺序读取历史正文和卡片。
    def versions(self, project_id):
        self.get(project_id)
        with self.lock:
            return [{**dict(row), 'card': json.loads(row['card'])} for row in
                    self.conn.execute('SELECT version,draft,card FROM versions WHERE project_id=? ORDER BY version', (project_id,))]

    # 外部请求前持久化占额，避免请求失败或进程重启后额度被重置。
    def reserve_call(self, project_id, task):
        # 在外部请求之前持久计数：异常、重启不会获得免费重置。
        with self.lock, self.conn:
            self.conn.execute('BEGIN IMMEDIATE')
            limit = self.conn.execute('SELECT max_calls FROM projects WHERE id=?', (project_id,)).fetchone()[0]
            used = self.conn.execute('SELECT count(*) FROM calls WHERE project_id=?', (project_id,)).fetchone()[0]
            if used >= limit:
                raise BudgetExceeded('已达到项目累计模型调用上限')
            return self.conn.execute('INSERT INTO calls(project_id,task,status) VALUES (?,?,?)',
                                     (project_id, task, 'started')).lastrowid

    # 补充本次调用结果和 token 用量；不是费用结算。
    def finish_call(self, call_id, status, usage=None):
        with self.lock, self.conn:
            self.conn.execute('UPDATE calls SET status=?, usage=? WHERE id=?', (status, dump(usage or {}), call_id))

    def close(self):
        self.conn.close()
