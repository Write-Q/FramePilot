"""旧单剧本流程 → 默认章节的单向兼容桥。

fp_versions 暂时仍是旧入口正文权威。只追加相同内容的领域版本；禁止静默
覆盖差异。后续多章节服务不得编辑这个兼容剧本后再反向写入旧快照。
"""
from uuid import UUID, uuid5
import json
from sqlalchemy import text, create_engine

_NAMESPACE = UUID('d44c1f37-b70d-4d29-9fd0-04b174fd37b6')


def domain_id(project_id, kind):
    return uuid5(_NAMESPACE, str(project_id)+':'+kind).hex


def sync_project(conn, project_id):
    # 父行锁同时保护初始化、历史追加和指针更新；不在模型调用时持锁。
    project = conn.execute(text('SELECT * FROM fp_projects WHERE id=:id FOR UPDATE'), {'id':project_id}).mappings().one()
    state = project['snapshot'].get('state', {})
    args = dict(project=project_id, chapter=domain_id(project_id,'chapter'), script=domain_id(project_id,'script'),
                input=domain_id(project_id,'input:1'), original=state.get('original_story',''),
                constraints=state.get('constraints',''), name=(state.get('original_story','').splitlines() or ['未命名项目'])[0].strip()[:80] or '未命名项目')
    conn.execute(text("INSERT INTO fp_project_details(project_id,name) VALUES (:project,:name) ON CONFLICT DO NOTHING"),args)
    conn.execute(text("INSERT INTO fp_chapters(id,project_id,title,position) VALUES (:chapter,:project,'默认章节',1) ON CONFLICT (id) DO NOTHING"),args)
    conn.execute(text("INSERT INTO fp_scripts(id,project_id,chapter_id) VALUES (:script,:project,:chapter) ON CONFLICT (id) DO NOTHING"),args)
    conn.execute(text("INSERT INTO fp_chapter_input_versions(id,project_id,chapter_id,version_no,original_story,constraints) VALUES (:input,:project,:chapter,1,:original,:constraints) ON CONFLICT (id) DO NOTHING"),args)
    # 原始输入不可被旧快照的意外变化悄悄替换。
    old_input=conn.execute(text('SELECT original_story,constraints FROM fp_chapter_input_versions WHERE id=:input'),args).one()
    if tuple(old_input)!=(args['original'],args['constraints']):
        raise ValueError('原始输入与领域存档不一致，停止同步；请通过新输入版本表达变更。')
    rows=conn.execute(text('SELECT version,draft,card FROM fp_versions WHERE project_id=:project ORDER BY version'),args).mappings().all()
    parent=None
    for row in rows:
        values={**args,'id':domain_id(project_id,'version:'+str(row['version'])), 'version':row['version'],
                'body':row['draft'],'card':json.dumps(row['card'],ensure_ascii=False),'parent':parent}
        existing=conn.execute(text('SELECT body,card FROM fp_script_versions WHERE id=:id'),values).mappings().first()
        if existing:
            if existing['body']!=row['draft'] or existing['card']!=row['card']:
                raise ValueError('旧剧本与领域历史版本内容不一致，停止同步以保留历史。')
        else:
            conn.execute(text('INSERT INTO fp_script_versions(id,project_id,script_id,chapter_id,version_no,parent_version_id,input_version_id,body,card) VALUES (:id,:project,:script,:chapter,:version,:parent,:input,:body,CAST(:card AS jsonb))'),values)
        parent=values['id']
    # 不覆盖已切换到非兼容版本的剧本：此类冲突必须显式处理。
    current=conn.execute(text('SELECT current_version_id FROM fp_scripts WHERE id=:script FOR UPDATE'),args).scalar_one()
    ids={domain_id(project_id,'version:'+str(row['version'])) for row in rows}
    if current is not None and current not in ids:
        raise ValueError('默认剧本已由新流程更新，不能继续通过旧入口写入。')
    if parent and current!=parent:
        conn.execute(text('UPDATE fp_scripts SET current_version_id=:current,row_version=row_version+1 WHERE id=:script'),dict(args,current=parent))


def backfill(url):
    engine=create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(718302612)'))
            ids=conn.execute(text('SELECT id FROM fp_projects ORDER BY id')).scalars().all()
            for project_id in ids: sync_project(conn, project_id)
            return len(ids)
    finally: engine.dispose()


def sync_project_on_psycopg(conn, project_id):
    """在 SQLite 导入已有 psycopg 事务中复用桥接，不提交或关闭调用者连接。"""
    from psycopg.rows import dict_row
    from sqlalchemy.dialects.postgresql.psycopg import dialect
    class Result:
        def __init__(self, rows): self.rows,self.mapping=rows,False
        def mappings(self): self.mapping=True; return self
        def one(self):
            if len(self.rows)!=1: raise ValueError('兼容同步要求唯一记录')
            return self.rows[0] if self.mapping else tuple(self.rows[0].values())
        def first(self):
            return self.rows[0] if self.rows else None
        def all(self): return self.rows
        def scalar_one(self): return next(iter(self.one()))
    class Adapter:
        def execute(self, statement, parameters=None):
            compiled=statement.compile(dialect=dialect())
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(str(compiled),parameters or {})
                return Result(cursor.fetchall() if cursor.description else [])
    sync_project(Adapter(),project_id)
