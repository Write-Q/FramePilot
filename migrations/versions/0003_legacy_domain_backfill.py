"""将旧项目历史回填到默认章节。算法冻结，不导入未来应用实现。"""
from alembic import op
revision = '0003_legacy_domain_backfill'
down_revision = '0002_domain_foundation'
branch_labels = None
depends_on = None

from uuid import UUID, uuid5
import json
from sqlalchemy import text

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



def upgrade():
    conn=op.get_bind()
    conn.execute(text('SELECT pg_advisory_xact_lock(718302612)'))
    # 仅在原业务表稳定时导入。升级事务阻止旧应用插入或更新。
    conn.execute(text('LOCK TABLE fp_projects, fp_versions IN SHARE ROW EXCLUSIVE MODE'))
    for project_id in conn.execute(text('SELECT id FROM fp_projects ORDER BY id')).scalars().all():
        sync_project(conn, project_id)


def downgrade():
    # 回退版本号不删除用户数据；新表由 0002 的有保护回退管理。
    pass
