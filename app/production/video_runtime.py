"""Durable submit/poll orchestration; providers and real video validation are opt-in."""
from datetime import datetime, timedelta, timezone
import os
import re
from uuid import uuid4

from pydantic import Field
import sqlalchemy as sa

from app.models import domain_tables as domain, production_tables as tables
from app.production.chat import PlannerError
from app.production.contracts import Contract, ModelConfig, ProfileRef
from app.production.media_io import MediaFiles, MAX_IMAGE_BYTES
from app.production.media_service import MediaService
from app.production.planning import digest
from app.production.store import InvalidProduction, ProductionConflict
from app.production.video_input import VideoAdapter, VideoPoll, VideoSubmission, build_video_input
from app.production.video_files import VideoFiles

MAX_VIDEO_RUNS = 100
POLL_INTERVAL_SECONDS = 30
MAX_VIDEO_BYTES = 256 * 1024 * 1024
ACTIVE = ('queued', 'submitting', 'submitted', 'polling')
ERRORS = {
    'validator_unavailable': '尚未接入实际视频解码和存储校验器，未提交生成。',
    'unsupported_adapter': '当前没有此配置对应的可执行视频适配器。',
    'source_changed': '来源、分镜或已选首帧已变化，未提交生成。',
    'input_unavailable': '固定首帧无法读取或校验，未提交生成。',
    'provider_error': '视频服务明确返回失败，未自动重新提交。',
    'outcome_unknown': '提交结果未知，请核对供应商；不会自动重新提交。',
    'interrupted': '已人工标记结果未知；外部请求未被取消，晚到结果不会覆盖记录。',
    'poll_error': '查询暂时失败，保留原外部任务标识并按间隔继续查询。',
    'poll_recovered': '已恢复查询，将仅查询原任务，不重新提交。',
    'invalid_output': '视频输出未通过实际媒体校验，未采用结果。',
    'storage_error': '视频输出保存失败，请核对供应商结果。',
}


class VideoRequest(Contract):
    expected_version: int = Field(ge=1, strict=True)
    shot_key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    profile: ProfileRef
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class VideoRuntime:
    def __init__(self, store, adapters=None, files=None):
        self.store = store
        self.adapters = dict(adapters or {})
        self.files = files if files is not None else VideoFiles()
        self.images = MediaService(store, files=MediaFiles(os.getenv('FRAMEPILOT_MEDIA_ROOT')))

    def _run(self, conn, project, series, identity):
        t = tables['video_runs']
        row = conn.execute(sa.select(t).where(t.c.id == identity, t.c.project_id == project)).mappings().first()
        if row is None or row['manifest']['storyboard_id'] != series:
            raise KeyError(identity)
        return row

    def _selected(self, conn, project):
        r, s = tables['video_runs'], tables['video_selections']
        rows = conn.execute(sa.select(r).join(s, sa.and_(s.c.project_id == r.c.project_id,
            s.c.run_id == r.c.id)).where(r.c.project_id == project).order_by(s.c.id)).mappings()
        selected = {}
        for row in rows:
            selected[(row['storyboard_version_id'], row['shot_key'])] = row['id']
        return selected

    def _serialize(self, row, board, selected):
        applicable = (row['storyboard_version_id'] == board['version_id']
            and board['version'] == board['current_version'] and board['confirmation_effective'])
        return {'id': row['id'], 'version': row['manifest']['version'], 'shot_key': row['shot_key'],
            'status': row['status'], 'kind': 'video', 'external_id': row['external_id'],
            'error_code': row['error_code'], 'error': ERRORS.get(row['error_code'], ''),
            'selected': selected.get((row['storyboard_version_id'], row['shot_key'])) == row['id'],
            'applicable': bool(applicable), 'manifest': row['manifest'], 'output': row['output'],
            'media_url': (f'/api/production/projects/{row["project_id"]}/storyboards/{row["manifest"]["storyboard_id"]}/video-runs/{row["id"]}/media'
                if row['status'] == 'succeeded' and isinstance(self.files, VideoFiles) else None),
            'prompt': row['manifest']['packet']['prompt'], 'duration_ms': row['manifest']['packet']['duration_ms'],
            'first_frame': row['manifest']['packet']['first_frame'],
            'idempotency_key': row['idempotency_key'],
            **{key: row[key].isoformat() if row[key] else None for key in
               ('created_at', 'started_at', 'finished_at', 'next_poll_at')}}

    def list(self, project, series, version=None):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            board = self.store._read(conn, project, series, version)
            t, b = tables['video_runs'], domain['storyboard_versions']
            rows = conn.execute(sa.select(t).join(b, sa.and_(b.c.id == t.c.storyboard_version_id,
                b.c.project_id == t.c.project_id)).where(t.c.project_id == project,
                b.c.breakdown_version_id == series).order_by(t.c.created_at.desc(), t.c.id)).mappings().all()
            selected = self._selected(conn, project)
            return {'runs': [self._serialize(row, board, selected) for row in rows],
                    'selections': list(selected.values()), 'max_runs': MAX_VIDEO_RUNS}

    def _adapter(self, config):
        adapter = self.adapters.get(config.adapter)
        if config.purpose != 'video' or adapter is None or not isinstance(adapter, VideoAdapter):
            raise InvalidProduction('请选择已注册执行器的视频配置；当前没有通用视频 HTTP 协议')
        if not config.capabilities.first_frame:
            raise InvalidProduction('此视频配置未声明支持首帧输入')
        if config.parameters.model_dump(exclude_none=True) or config.reasoning_protocol != 'none' or config.reasoning_levels:
            raise InvalidProduction('当前视频运行时不接收文本生成或思考参数')
        return adapter

    def create(self, project, series, request):
        request = VideoRequest.model_validate(request)
        t = tables['video_runs']
        fingerprint = digest({'storyboard_id': series, **request.model_dump(mode='json')})
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            existing = conn.execute(sa.select(t).where(t.c.project_id == project,
                t.c.idempotency_key == request.idempotency_key)).mappings().first()
            if existing:
                if existing['request_sha256'] != fingerprint:
                    raise ProductionConflict('幂等键已用于其他视频请求')
                return self._serialize(existing, self.store._read(conn, project, series), self._selected(conn, project))
            board = self.images._board(conn, project, series, request.expected_version)
            config = ModelConfig.model_validate(self.store._profile(conn, request.profile.profile_id, request.profile.version)['config'])
            self._adapter(config)
            if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project)).scalar_one() >= MAX_VIDEO_RUNS:
                raise ProductionConflict('已达到项目累计100次视频请求上限，取消和失败保留记录')
            if conn.execute(sa.select(t.c.id).where(t.c.project_id == project,
                t.c.storyboard_version_id == board['version_id'], t.c.shot_key == request.shot_key,
                t.c.status.in_(ACTIVE))).first():
                raise ProductionConflict('此镜头已有活动视频任务，请先刷新记录')
            image_id = self.images._selected(conn, project).get((board['version_id'], request.shot_key, 'first'))
            if image_id is None:
                raise ProductionConflict('请先选用当前版本、当前镜头的成功首帧')
            image = dict(self.images._run(conn, project, series, image_id)) | {'selected': True}
            try:
                packet = build_video_input(board, request.shot_key, image)
            except ValueError as exc:
                raise InvalidProduction(str(exc)) from None
            if config.capabilities.max_duration_ms is not None and packet['duration_ms'] > config.capabilities.max_duration_ms:
                raise InvalidProduction('镜头时长超过配置声明的上限，请调整分镜或配置')
            manifest = {'storyboard_id': series, 'version': board['version'], 'source_version_id': board['source_version_id'],
                'board_sha256': digest(board['content']), 'packet': packet, 'profile': request.profile.model_dump(),
                'adapter': config.adapter, 'model': config.model}
            identity = uuid4().hex
            conn.execute(t.insert().values(id=identity, project_id=project, storyboard_version_id=board['version_id'],
                shot_id=image['shot_id'], shot_key=request.shot_key, first_frame_run_id=image_id,
                first_frame_media_id=image['media_id'], profile_id=request.profile.profile_id,
                profile_version=request.profile.version, idempotency_key=request.idempotency_key,
                request_sha256=fingerprint, manifest=manifest, status='queued'))
            return self._serialize(self._run(conn, project, series, identity), board, self._selected(conn, project))

    def _transition(self, project, series, identity, sources, target, error=None):
        t = tables['video_runs']
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._run(conn, project, series, identity)
            if row['status'] in sources:
                values = {'status': target, 'claim_id': None, 'error_code': error,
                    'next_poll_at': sa.func.now() if target == 'submitted' else None,
                    'finished_at': None if target == 'submitted' else sa.func.now()}
                changed = conn.execute(t.update().where(t.c.id == identity, t.c.status == row['status'],
                    t.c.claim_id.is_not_distinct_from(row['claim_id'])).values(**values).returning(t.c.id)).scalar_one_or_none()
                if changed is None:
                    raise ProductionConflict('任务状态已变化，请刷新记录')
            elif row['status'] != target or target == 'submitted':
                raise ProductionConflict('当前任务状态不能执行此操作')
            return self._serialize(self._run(conn, project, series, identity),
                self.store._read(conn, project, series), self._selected(conn, project))

    def cancel(self, project, series, identity):
        return self._transition(project, series, identity, ('queued',), 'cancelled')

    def abandon(self, project, series, identity):
        return self._transition(project, series, identity, ('submitting', 'submitted', 'polling'), 'unknown', 'interrupted')

    def recover_poll(self, project, series, identity):
        return self._transition(project, series, identity, ('polling',), 'submitted', 'poll_recovered')

    def select(self, project, series, identity, expected_version):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._run(conn, project, series, identity)
            board = self.images._board(conn, project, series, expected_version)
            if row['status'] != 'succeeded' or row['storyboard_version_id'] != board['version_id']:
                raise ProductionConflict('仅能选用当前已确认版本的成功视频')
            if self._selected(conn, project).get((board['version_id'], row['shot_key'])) != identity:
                conn.execute(tables['video_selections'].insert().values(project_id=project, run_id=identity))
            return self._serialize(row, board, self._selected(conn, project))

    def _validator_ready(self):
        return getattr(self.files, 'validated_video', False) is True and callable(getattr(self.files, 'put', None))

    def media(self, project, series, identity):
        with self.store.engine.begin() as conn:
            row = self._run(conn, project, series, identity)
            if row['status'] != 'succeeded' or not row['output'] or not isinstance(self.files, VideoFiles):
                raise KeyError(identity)
            output = dict(row['output'])
        try:
            return self.files.verify(output), output['mime_type']
        except (ValueError, OSError):
            raise KeyError(identity) from None

    def _preflight(self, row):
        t = tables['video_runs']
        with self.store.engine.begin() as conn:
            self.store._project(conn, row['project_id'], lock=True)
            current = conn.execute(sa.select(t).where(t.c.id == row['id'])).mappings().one()
            if current['status'] != row['status'] or current['claim_id'] != row['claim_id']:
                return None
            config = ModelConfig.model_validate(self.store._profile(conn, row['profile_id'], row['profile_version'])['config'])
            adapter = self._adapter(config)
            if row['status'] == 'polling':
                return config, adapter, None
            board = self.images._board(conn, row['project_id'], row['manifest']['storyboard_id'], row['manifest']['version'])
            if board['version_id'] != row['storyboard_version_id'] or digest(board['content']) != row['manifest']['board_sha256']:
                raise ProductionConflict('视频分镜版本已变化')
            if self.images._selected(conn, row['project_id']).get((board['version_id'], row['shot_key'], 'first')) != row['first_frame_run_id']:
                raise ProductionConflict('已选首帧变化')
            media = domain['media_files']
            image = conn.execute(sa.select(media).where(media.c.id == row['first_frame_media_id'],
                media.c.project_id == row['project_id'])).mappings().one()
        if not self._validator_ready():
            raise PlannerError('validator unavailable', 'validator_unavailable')
        from app.production.media_io import _inspect
        import hashlib
        path = self.images.files.path(image['storage_key'])
        with path.open('rb') as source:
            first_frame = source.read(MAX_IMAGE_BYTES + 1)
        if len(first_frame) != image['size_bytes'] or hashlib.sha256(first_frame).hexdigest() != image['checksum']:
            raise PlannerError('first frame checksum mismatch', 'input_unavailable')
        try:
            _inspect(first_frame, image['media_type'])
        except PlannerError:
            raise PlannerError('first frame invalid', 'input_unavailable') from None
        return config, adapter, first_frame

    def _save_output(self, result):
        if not self._validator_ready():
            raise PlannerError('validator unavailable', 'invalid_output')
        if len(result.output) > MAX_VIDEO_BYTES:
            raise ValueError('output too large')
        saved = self.files.put(result.output, result.mime_type)
        # Only explicit safe fields can cross the public boundary; never leak validator paths/logs.
        if (not isinstance(saved, dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}\.(mp4|webm)', str(saved.get('storage_key', '')))
                or not re.fullmatch(r'[a-f0-9]{64}', str(saved.get('checksum', '')))
                or type(saved.get('size_bytes')) is not int or saved['size_bytes'] != len(result.output)
                or saved.get('mime_type') != result.mime_type or not isinstance(saved.get('metadata'), dict)):
            raise ValueError('invalid video storage result')
        metadata = {key: saved['metadata'][key] for key in ('width', 'height', 'duration_ms')
                    if type(saved['metadata'].get(key)) is int and saved['metadata'][key] > 0}
        if len(metadata) != 3:
            raise ValueError('missing decoded video properties')
        return {key: saved[key] for key in ('storage_key', 'checksum', 'size_bytes', 'mime_type')} | {'metadata': metadata}

    def run_once(self):
        t = tables['video_runs']
        with self.store.engine.begin() as conn:
            row = conn.execute(sa.select(t).where(sa.or_(t.c.status == 'queued',
                sa.and_(t.c.status == 'submitted', t.c.next_poll_at <= sa.func.now())))
                .order_by(t.c.created_at, t.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if row is None:
                return False
            row = dict(row)
            claimed = 'submitting' if row['status'] == 'queued' else 'polling'
            claim_id = uuid4().hex
            conn.execute(t.update().where(t.c.id == row['id']).values(status=claimed, claim_id=claim_id,
                started_at=row['started_at'] or sa.func.now(), next_poll_at=None))
            row.update(status=claimed, claim_id=claim_id)
        status, error, output, external_id = None, None, None, row['external_id']
        submitted_call = False
        try:
            context = self._preflight(row)
            if context is None:
                return True
            config, adapter, first_frame = context
            if claimed == 'submitting':
                submitted_call = True
                response = adapter.submit(config, row['manifest']['packet'], first_frame)
                if not isinstance(response, VideoSubmission):
                    raise ValueError('invalid submission result')
                # The following transaction persists this identity before a later poll can claim it.
                external_id, status = response.external_id, 'submitted'
            else:
                response = adapter.poll(config, row['external_id'])
                if not isinstance(response, VideoPoll):
                    raise ValueError('invalid poll response')
                if response.status == 'succeeded':
                    try:
                        output = self._save_output(response)
                    except OSError:
                        raise PlannerError('storage failed', 'storage_error') from None
                    except (ValueError, TypeError, KeyError):
                        raise PlannerError('video validation failed', 'invalid_output') from None
                    status = 'succeeded'
                elif response.status == 'failed':
                    status, error = 'failed', 'provider_error'
                else:
                    status = 'submitted'
        except ProductionConflict:
            status, error = ('failed', 'source_changed') if claimed == 'submitting' else ('submitted', 'poll_error')
        except InvalidProduction:
            status, error = ('failed', 'unsupported_adapter') if claimed == 'submitting' else ('submitted', 'poll_error')
        except PlannerError as exc:
            if claimed == 'polling':
                status, error = ('failed', exc.code) if exc.code in ('invalid_output', 'storage_error') else ('submitted', 'poll_error')
            elif submitted_call:
                status, error = ('failed', 'provider_error') if exc.code == 'provider_error' else ('unknown', 'outcome_unknown')
            else:
                status, error = 'failed', exc.code if exc.code in ('validator_unavailable', 'input_unavailable') else 'input_unavailable'
        except Exception:
            if claimed == 'polling':
                status, error = 'submitted', 'poll_error'
            else:
                status, error = ('unknown', 'outcome_unknown') if submitted_call else ('failed', 'input_unavailable')
        with self.store.engine.begin() as conn:
            # Claim identity suppresses results from abandoned or manually recovered work.
            values = {'status': status, 'error_code': error, 'output': output, 'claim_id': None,
                'finished_at': None if status == 'submitted' else sa.func.now(),
                'next_poll_at': datetime.now(timezone.utc) + timedelta(seconds=POLL_INTERVAL_SECONDS) if status == 'submitted' else None}
            if claimed == 'submitting' and status == 'submitted':
                values['external_id'] = external_id
            conn.execute(t.update().where(t.c.id == row['id'], t.c.status == claimed,
                t.c.claim_id == claim_id).values(**values))
        return True
