"""SQLAlchemy 业务仓库；短事务在模型请求前提交，不占着锁等待网络。"""
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, func, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
from app.database import database_url
from app.models import Project, StoryVersion, ModelCall


class BudgetExceeded(RuntimeError):
    pass


class Repository:
    def __init__(self, url):
        self.engine = create_engine(database_url(url), pool_pre_ping=True,
                                    pool_size=5, max_overflow=5,
                                    connect_args={'connect_timeout': 10})
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create(self, project_id, state, max_calls):
        # 当前状态和暂停信息保存为快照，历史正文独立存储。
        with self.sessions.begin() as session:
            session.add(Project(id=project_id, snapshot={'state': state, 'interrupt': None},
                                max_calls=max_calls, created_at=datetime.now(timezone.utc)))

    def save(self, project_id, state, pending):
        with self.sessions.begin() as session:
            result = session.execute(update(Project).where(Project.id == project_id)
                .values(snapshot={'state': state, 'interrupt': pending}))
            if result.rowcount != 1:
                raise KeyError(project_id)

    def version(self, state):
        # 同一版本不覆盖；冲突处理替代 SQLite INSERT OR IGNORE。
        with self.sessions.begin() as session:
            session.execute(insert(StoryVersion).values(project_id=state['project_id'],
                version=state['version'], draft=state['draft'], card=state['card'])
                .on_conflict_do_nothing(index_elements=['project_id', 'version']))

    def get(self, project_id):
        with self.sessions() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise KeyError(project_id)
            calls = session.scalars(select(ModelCall).where(ModelCall.project_id == project_id)
                                    .order_by(ModelCall.id)).all()
            return {'id': project_id, **project.snapshot,
                    'created_at': project.created_at.isoformat(),
                    'max_calls': project.max_calls, 'calls_used': len(calls),
                    'calls': [{'task': c.task, 'status': c.status, 'usage': c.usage} for c in calls]}

    def versions(self, project_id):
        with self.sessions() as session:
            if session.get(Project, project_id) is None:
                raise KeyError(project_id)
            rows = session.scalars(select(StoryVersion).where(StoryVersion.project_id == project_id)
                                   .order_by(StoryVersion.version)).all()
            return [{'version': row.version, 'draft': row.draft, 'card': row.card} for row in rows]

    def reserve_call(self, project_id, task):
        # 行锁串行化同一项目的“检查余额＋写入账本”，不同连接也不能并发超额。
        with self.sessions.begin() as session:
            project = session.scalar(select(Project).where(Project.id == project_id).with_for_update())
            if project is None:
                raise KeyError(project_id)
            used = session.scalar(select(func.count()).select_from(ModelCall)
                                  .where(ModelCall.project_id == project_id))
            if used >= project.max_calls:
                raise BudgetExceeded('已达到项目累计模型调用上限')
            call = ModelCall(project_id=project_id, task=task, status='started', usage={})
            session.add(call)
            session.flush()
            return call.id

    def finish_call(self, call_id, status, usage=None):
        with self.sessions.begin() as session:
            session.execute(update(ModelCall).where(ModelCall.id == call_id)
                            .values(status=status, usage=usage or {}))

    def close(self):
        self.engine.dispose()
