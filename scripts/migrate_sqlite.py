"""离线迁移旧库：只读备份源库，将业务数据和图检查点原子导入空 PostgreSQL。"""
import argparse
from contextlib import closing
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from app.database import database_url, checkpoint_conninfo


def backup_source(source):
    """backup API 会包含 WAL 已提交内容；请先停服，保证两个库处于同一业务时刻。"""
    source = Path(source).resolve()
    for name in ('stories.sqlite3', 'checkpoints.sqlite3'):
        if not (source / name).is_file():
            raise ValueError('源目录必须同时包含业务库和检查点库。')
    target = source / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    target.mkdir(parents=True)
    for name in ('stories.sqlite3', 'checkpoints.sqlite3'):
        with closing(sqlite3.connect((source / name).as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(target / name)) as dst:
                src.backup(dst)
    return target


def migrate(source, url=None):
    value = database_url(url).render_as_string(hide_password=False)
    backup = backup_source(source)
    with closing(sqlite3.connect(backup / 'stories.sqlite3')) as legacy:
        legacy.row_factory = sqlite3.Row
        projects = [dict(r) for r in legacy.execute('SELECT * FROM projects')]
        versions = [dict(r) for r in legacy.execute('SELECT * FROM versions')]
        calls = [dict(r) for r in legacy.execute('SELECT * FROM calls ORDER BY id')]
    with SqliteSaver.from_conn_string(str(backup / 'checkpoints.sqlite3')) as old:
        checkpoints = list(old.list(None))
    thread_ids = {cp.config['configurable']['thread_id'] for cp in checkpoints}
    for row in projects:
        snapshot = json.loads(row['snapshot'])
        if snapshot['state']['status'] == 'running':
            raise ValueError('源库存在 running 项目，请先确认原任务已停止并处理其状态。')
        if snapshot.get('interrupt') and row['id'] not in thread_ids:
            raise ValueError('等待人工操作的项目缺少检查点，已停止导入。')
    # 业务表和图表使用同一连接/事务导入；任何异常都会整体回滚。
    with psycopg.connect(checkpoint_conninfo(value), autocommit=True, row_factory=dict_row) as conn:
        saver = PostgresSaver(conn)
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(718302611)')
            # 锁住目标表，阻止导入过程中应用写入；生产操作仍必须先停服。
            conn.execute('LOCK TABLE fp_projects, fp_versions, fp_calls, checkpoints, checkpoint_blobs, checkpoint_writes IN ACCESS EXCLUSIVE MODE')
            for table in ('fp_projects', 'fp_versions', 'fp_calls', 'checkpoints', 'checkpoint_blobs', 'checkpoint_writes'):
                if conn.execute('SELECT EXISTS (SELECT 1 FROM ' + table + ') AS occupied').fetchone()['occupied']:
                    raise ValueError('目标数据库非空，拒绝覆盖；请使用新的空数据库。')
            for row in projects:
                conn.execute('INSERT INTO fp_projects(id,snapshot,max_calls,created_at) VALUES (%s,%s,%s,%s)',
                             (row['id'], Jsonb(json.loads(row['snapshot'])), row['max_calls'], row['created_at']))
            for row in versions:
                conn.execute('INSERT INTO fp_versions(project_id,version,draft,card) VALUES (%s,%s,%s,%s)',
                             (row['project_id'], row['version'], row['draft'], Jsonb(json.loads(row['card']))))
            for row in calls:
                conn.execute('INSERT INTO fp_calls(id,project_id,task,status,usage) VALUES (%s,%s,%s,%s,%s)',
                             (row['id'], row['project_id'], row['task'], row['status'], Jsonb(json.loads(row['usage']))))
            # 按时间从旧到新导入，保留 checkpoint_id、父检查点和 channel_versions。
            for item in reversed(checkpoints):
                base = item.parent_config or {'configurable': {
                    'thread_id': item.config['configurable']['thread_id'],
                    'checkpoint_ns': item.config['configurable'].get('checkpoint_ns', '')}}
                saved = saver.put(base, item.checkpoint, item.metadata, item.checkpoint['channel_versions'])
                writes = defaultdict(list)
                for task_id, channel, val in item.pending_writes or []:
                    writes[task_id].append((channel, val))
                for task_id, values in writes.items():
                    saver.put_writes(saved, values, task_id)
            # 在提交前验证图内容与待处理写入，避免只迁正文却失去暂停位置。
            for item in checkpoints:
                restored = saver.get_tuple(item.config)
                if (restored is None or restored.checkpoint != item.checkpoint
                        or restored.parent_config != item.parent_config
                        or restored.pending_writes != item.pending_writes):
                    raise ValueError('检查点导入校验失败，事务已回滚。')
            conn.execute("SELECT setval(pg_get_serial_sequence('fp_calls','id'), COALESCE((SELECT MAX(id) FROM fp_calls),1), EXISTS(SELECT 1 FROM fp_calls))")
    return {'projects':len(projects), 'versions':len(versions), 'calls':len(calls),
            'checkpoints':len(checkpoints), 'backup':str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--confirm-stopped', action='store_true', help='确认旧服务已停止且目标库没有应用写入')
    args = parser.parse_args()
    if not args.confirm_stopped:
        parser.error('先停止应用，再传入 --confirm-stopped；不要在运行中迁移。')
    try:
        report = migrate(args.source)
    except Exception as exc:
        # 数据库异常可能包含参数值，CLI 不输出源故事、SQL 参数或连接密码。
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        raise SystemExit('迁移未完成；源库和备份均保留。原因：' + message) from None
    print(json.dumps(report, ensure_ascii=False))
