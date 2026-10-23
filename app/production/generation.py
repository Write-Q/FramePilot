"""分镜规划预约与原子落库；模型请求在所有数据库事务之外。"""
from uuid import uuid4

import sqlalchemy as sa
from pydantic import ValidationError

from app.models import domain_tables as domain, production_tables as tables
from app.production.chat import ChatPlanner, PlannerError
from app.production.contracts import CreateStoryboard, ModelConfig, StoryboardContent
from app.production.planning import build_packet, digest, review_board
from app.production.store import ProductionConflict, InvalidProduction
from app.production.reasoning import choose_effort, execution_manifest, request_identity

MAX_RUNS = 10
ERRORS = {'invalid_output': '模型输出未通过分镜结构或来源校验，未创建分镜。',
          'output_truncated': '模型输出达到长度上限，结果未采用。可降低思考等级，或在模型支持范围内调整配置的输出预算后手动重试；未自动重试。',
          'source_changed': '生成期间来源剧本发生变化，未采用过期结果。',
          'outcome_unknown': '请求超时或连接中断，外部执行结果可能未知；未自动重试。',
          'provider_error': '文本服务请求失败，请检查服务和配置；未自动重试。',
          'missing_key': '未找到配置指定的密钥环境变量，请在本机设置后重启服务。',
          'interrupted': '已标记中断；这不取消外部请求，稍后返回的结果也不会采用。'}


class StoryboardGenerator:
    def __init__(self, store, provider=None):
        self.store = store
        self.provider = provider or ChatPlanner()

    def _read(self, conn, project, identity):
        row = conn.execute(sa.select(tables['runs']).where(tables['runs'].c.project_id == project,
                           tables['runs'].c.id == identity)).mappings().first()
        if row is None:
            raise KeyError(identity)
        result = {key: row[key] for key in ('id', 'project_id', 'idempotency_key', 'manifest', 'status', 'error_code', 'usage')}
        result.update(created_at=row['created_at'].isoformat(),
                      finished_at=row['finished_at'].isoformat() if row['finished_at'] else None,
                      error=ERRORS.get(row['error_code'], ''), board=None, review=None, max_runs=MAX_RUNS)
        if row['storyboard_version_id']:
            board = conn.execute(sa.select(domain['storyboard_versions']).where(
                domain['storyboard_versions'].c.id == row['storyboard_version_id'],
                domain['storyboard_versions'].c.project_id == project)).mappings().one()
            result['board'] = self.store._read(conn, project, board['breakdown_version_id'], board['version_no'])
            body = conn.execute(sa.select(domain['script_versions'].c.body).where(
                domain['script_versions'].c.id == row['source_version_id'],
                domain['script_versions'].c.project_id == project)).scalar_one()
            result['review'] = review_board(StoryboardContent.model_validate(result['board']['content']), body)
        return result

    def list_runs(self, project):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            self.store._project(conn, project)
            identities = conn.execute(sa.select(tables['runs'].c.id).where(tables['runs'].c.project_id == project)
                                     .order_by(tables['runs'].c.created_at.desc(), tables['runs'].c.id)).scalars().all()
            return [self._read(conn, project, identity) for identity in identities]

    def abandon(self, project, identity):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            run = self._read(conn, project, identity)
            if run['status'] == 'running':
                conn.execute(tables['runs'].update().where(tables['runs'].c.id == identity).values(
                    status='abandoned', error_code='interrupted', finished_at=sa.func.now()))
            return self._read(conn, project, identity)

    def generate(self, project, request):
        table = tables['runs']
        fingerprint = digest(request_identity(request))
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            existing = conn.execute(sa.select(table).where(table.c.project_id == project,
                       table.c.idempotency_key == request.idempotency_key)).mappings().first()
            if existing:
                if existing['request_sha256'] != fingerprint:
                    raise ProductionConflict('幂等键已用于不同参数，请刷新运行记录后明确发起新请求')
                return self._read(conn, project, existing['id'])
            if conn.execute(sa.select(table.c.id).where(table.c.project_id == project, table.c.status == 'running')).first():
                raise ProductionConflict('项目已有运行中的分镜请求，请刷新记录或明确标记中断')
            used = conn.execute(sa.select(sa.func.count()).select_from(table).where(table.c.project_id == project)).scalar_one()
            if used >= MAX_RUNS:
                raise ProductionConflict('已达到项目累计十次分镜请求上限（与编剧额度分别计算）')
            source, state = self.store._source(conn, project, request.source_version)
            profile = self.store._profile(conn, request.profile.profile_id, request.profile.version)
            config = ModelConfig.model_validate(profile['config'])
            if config.purpose != 'text' or config.adapter != 'openai_chat':
                raise InvalidProduction('分镜生成请选择用途为text、适配器为openai_chat的模型配置')
            config = choose_effort(config, request.reasoning_effort)
            packet = build_packet(source['body'], state.get('card', {}), state.get('constraints', ''), request)
            identity = uuid4().hex
            manifest = packet['manifest'] | execution_manifest(config) | {'request': request_identity(request),
                        'source_sha256': digest(source['body']), 'source_version_id': source['id'],
                        'context_sha256': digest({'card': state.get('card', {}), 'constraints': state.get('constraints', '')})}
            conn.execute(table.insert().values(id=identity, project_id=project,
                idempotency_key=request.idempotency_key, request_sha256=fingerprint,
                source_version_id=source['id'], profile_id=request.profile.profile_id,
                profile_version=request.profile.version, manifest=manifest, status='running'))
        usage = {}
        error = None
        try:
            output, usage = self.provider.generate(config, packet['messages'])
            content = StoryboardContent.model_validate(output)
            if (len(content.shots) != request.target_shots or content.aspect_ratio != request.aspect_ratio
                    or content.bindings or (request.visual_style and content.visual_style != request.visual_style)):
                raise InvalidProduction('输出镜头数、画幅、风格或配置绑定不符合请求')
            content.bindings = {'text': request.profile}
            with self.store.engine.begin() as conn:
                self.store._project(conn, project, lock=True)
                run = self._read(conn, project, identity)
                if run['status'] != 'running':
                    return run
                _, latest_state = self.store._source(conn, project, request.source_version)
                if digest({'card': latest_state.get('card', {}), 'constraints': latest_state.get('constraints', '')}) != manifest['context_sha256']:
                    raise ProductionConflict('来源的解释或创作约束已变化，请重新规划')
                board = self.store._create_storyboard(conn, project,
                    CreateStoryboard(source_version=request.source_version, content=content),
                    provenance={'run_id': identity, **manifest})
                conn.execute(table.update().where(table.c.id == identity).values(status='succeeded', usage=usage,
                             storyboard_version_id=board['version_id'], finished_at=sa.func.now()))
                return self._read(conn, project, identity)
        except PlannerError as exc:
            error, usage = exc.code, exc.usage
        except (ValidationError, InvalidProduction, TypeError, ValueError) as exc:
            error = 'source_changed' if isinstance(exc, ProductionConflict) else 'invalid_output'
        # 不存储原始模型内容或异常文本，避免网关错误回显凭证。
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            conn.execute(table.update().where(table.c.id == identity, table.c.status == 'running').values(
                status='failed', error_code=error, usage=usage, finished_at=sa.func.now()))
            return self._read(conn, project, identity)

    def review(self, project, identity, version=None):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            board = self.store._read(conn, project, identity, version)
            body = conn.execute(sa.select(domain['script_versions'].c.body).where(
                domain['script_versions'].c.project_id == project,
                domain['script_versions'].c.id == board['source_version_id'])).scalar_one()
            return review_board(StoryboardContent.model_validate(board['content']), body)
