"""显式的单次文字分镜审核；报告保留原版本，不修改或确认分镜。"""
from uuid import uuid4

import sqlalchemy as sa
from pydantic import ValidationError

from app.models import domain_tables as domain, production_tables as tables
from app.production.chat import ChatPlanner, PlannerError
from app.production.contracts import ModelConfig
from app.production.generation import ERRORS
from app.production.planning import digest
from app.production.review_contracts import ReviewReport
from app.production.review_prompt import build_review_packet, validate_evidence
from app.production.store import InvalidProduction, ProductionConflict
from app.production.reasoning import choose_effort, execution_manifest, request_identity

MAX_REVIEWS = 10


def context_digest(state):
    return digest({'card': state.get('card', {}), 'constraints': state.get('constraints', '')})


class StoryboardReviewer:
    def __init__(self, store, provider=None):
        self.store = store
        self.provider = provider or ChatPlanner()

    def _read(self, conn, project, identity):
        table = tables['review_runs']
        row = conn.execute(sa.select(table).where(table.c.project_id == project, table.c.id == identity)).mappings().first()
        if row is None:
            raise KeyError(identity)
        target = conn.execute(sa.select(domain['storyboard_versions']).where(
            domain['storyboard_versions'].c.project_id == project,
            domain['storyboard_versions'].c.id == row['storyboard_version_id'])).mappings().one()
        board = self.store._read(conn, project, target['breakdown_version_id'], target['version_no'])
        state = self.store._project(conn, project)
        stale = []
        if board['version'] != board['current_version']:
            stale.append('board_changed')
        if not board['source_current'] or not board['source_confirmed']:
            stale.append('source_changed')
        if context_digest(state) != row['manifest']['context_sha256']:
            stale.append('context_changed')
        result = {key: row[key] for key in ('id', 'project_id', 'idempotency_key', 'source_version_id',
                  'storyboard_version_id', 'profile_id', 'profile_version', 'manifest', 'status', 'error_code', 'usage', 'report')}
        return result | {'storyboard_id': board['id'], 'version': board['version'],
                         'applicable': row['status'] == 'succeeded' and not stale, 'stale_reasons': stale,
                         'error': ('审核输出未通过结构或原文证据校验，未采用报告。' if row['error_code'] == 'invalid_output'
                                   else ERRORS.get(row['error_code'], '')),
                         'created_at': row['created_at'].isoformat(),
                         'finished_at': row['finished_at'].isoformat() if row['finished_at'] else None,
                         'max_runs': MAX_REVIEWS}

    def list_runs(self, project, series):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            self.store._read(conn, project, series)
            table, boards = tables['review_runs'], domain['storyboard_versions']
            identities = conn.execute(sa.select(table.c.id).join(boards, table.c.storyboard_version_id == boards.c.id).where(
                table.c.project_id == project, boards.c.breakdown_version_id == series).order_by(
                table.c.created_at.desc(), table.c.id)).scalars().all()
            used = conn.execute(sa.select(sa.func.count()).select_from(table).where(table.c.project_id == project)).scalar_one()
            return [self._read(conn, project, identity) | {'used_runs': used} for identity in identities]

    def abandon(self, project, series, identity):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            run = self._read(conn, project, identity)
            if run['storyboard_id'] != series:
                raise KeyError(identity)
            if run['status'] == 'running':
                conn.execute(tables['review_runs'].update().where(tables['review_runs'].c.id == identity).values(
                    status='abandoned', error_code='interrupted', finished_at=sa.func.now()))
            return self._read(conn, project, identity)

    def review(self, project, series, request):
        table = tables['review_runs']
        fingerprint = digest({'storyboard_id': series, **request_identity(request)})
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            existing = conn.execute(sa.select(table).where(table.c.project_id == project,
                table.c.idempotency_key == request.idempotency_key)).mappings().first()
            if existing:
                if existing['request_sha256'] != fingerprint:
                    raise ProductionConflict('幂等键已用于不同审核参数，请刷新记录后明确发起新请求')
                return self._read(conn, project, existing['id'])
            if conn.execute(sa.select(table.c.id).where(table.c.project_id == project, table.c.status == 'running')).first():
                raise ProductionConflict('项目已有运行中的文字分镜审核，请刷新记录或明确标记中断')
            used = conn.execute(sa.select(sa.func.count()).select_from(table).where(table.c.project_id == project)).scalar_one()
            if used >= MAX_REVIEWS:
                raise ProductionConflict('已达到项目累计十次文字分镜审核上限（与编剧、分镜生成分别计算）')
            board = self.store._read(conn, project, series)
            if board['version'] != request.expected_version:
                raise ProductionConflict('分镜版本已变化，请保存或刷新后重新审核')
            source, state = self.store._source(conn, project, board['source_version'])
            profile = self.store._profile(conn, request.profile.profile_id, request.profile.version)
            config = ModelConfig.model_validate(profile['config'])
            if config.purpose != 'review' or config.adapter != 'openai_chat':
                raise InvalidProduction('文字分镜审核请选择用途为 review、适配器为 openai_chat 的配置')
            config = choose_effort(config, request.reasoning_effort)
            packet = build_review_packet(source['body'], state.get('card', {}), state.get('constraints', ''), board['content'])
            identity = uuid4().hex
            manifest = packet['manifest'] | execution_manifest(config) | {'request': request_identity(request),
                'source_sha256': digest(source['body']), 'context_sha256': context_digest(state),
                'board_sha256': digest(board['content']), 'storyboard_id': series}
            conn.execute(table.insert().values(id=identity, project_id=project,
                idempotency_key=request.idempotency_key, request_sha256=fingerprint,
                source_version_id=source['id'], storyboard_version_id=board['version_id'],
                profile_id=request.profile.profile_id, profile_version=request.profile.version,
                manifest=manifest, status='running'))
        usage, report, error = {}, None, None
        try:
            output, usage = self.provider.generate(config, packet['messages'])
            validated = ReviewReport.model_validate(output)
            validate_evidence(validated, board['content'], source['body'])
            report = validated.model_dump(mode='json')
        except PlannerError as exc:
            error, usage = exc.code, exc.usage
        except (ValidationError, InvalidProduction, TypeError, ValueError, KeyError):
            error = 'invalid_output'
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            # 中断的请求不能由迟到结果恢复；期间改稿时报告仍绑定原始版本并显示过期。
            conn.execute(table.update().where(table.c.id == identity, table.c.status == 'running').values(
                status='failed' if error else 'succeeded', error_code=error, usage=usage,
                **({'report': report} if report is not None else {}), finished_at=sa.func.now()))
            return self._read(conn, project, identity)
