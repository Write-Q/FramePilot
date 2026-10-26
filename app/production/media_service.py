"""Durable single-image queue. Provider calls never run inside a DB transaction."""
from uuid import uuid4
import sqlalchemy as sa

from app.models import domain_tables as domain, production_tables as tables
from app.production.chat import PlannerError
from app.production.contracts import ModelConfig
from app.production.frame_prompt import build_frame_prompt
from app.production.media_io import ImageAdapter, MediaFiles
from app.production.planning import digest
from app.production.store import InvalidProduction, ProductionConflict

ERRORS = {
    'outcome_unknown': '外部执行结果未知，请核对服务端；不会自动重试。',
    'interrupted': '已标记结果未知；这不会取消外部请求，晚到结果不会覆盖本记录。',
    'provider_error': '图像服务请求失败，请检查服务配置；未自动重试。',
    'missing_key': '未找到图像配置所需密钥环境变量，请配置生成服务后重试。',
    'unsupported_output': '当前接口只接收 base64 图片；服务返回了尚不支持的格式。',
    'invalid_output': '图片格式、解码或尺寸验证失败，未采用输出。',
    'invalid_input': '图像请求参数不受支持，请检查配置和尺寸。',
    'unsupported_adapter': '当前没有可执行的图像适配器。',
    'source_changed': '分镜或来源已变化，排队任务没有调用模型。',
    'storage_error': '图片存储未完成，外部可能已生成，请核对后再决定是否重试。',
    'internal_error': '生成服务中断，结果未知，请核对后处理。',
}
MAX_MEDIA_RUNS = 100


class MediaService:
    def __init__(self, store, files=None):
        self.store = store
        self.files = files or MediaFiles()

    def _run(self, conn, project, series, identity):
        t = tables['media_runs']
        row = conn.execute(sa.select(t).where(t.c.id == identity, t.c.project_id == project)).mappings().first()
        if row is None or row['manifest']['storyboard_id'] != series:
            raise KeyError(identity)
        return row

    def _board(self, conn, project, series, version):
        board = self.store._read(conn, project, series, version)
        if board['version'] != board['current_version'] or not board['confirmation_effective']:
            raise ProductionConflict('需要已保存并确认的当前分镜和来源剧本版本')
        return board

    @staticmethod
    def _slot(row):
        return (row['storyboard_version_id'], row['shot_key'], row['frame_role'])

    def _selected(self, conn, project):
        r, s = tables['media_runs'], tables['media_selections']
        rows = conn.execute(sa.select(r).join(s, sa.and_(s.c.project_id == r.c.project_id, s.c.run_id == r.c.id))
            .where(s.c.project_id == project).order_by(s.c.id)).mappings()
        selected = {}
        for row in rows:
            selected[self._slot(row)] = row['id']
        return selected

    def _serialize(self, conn, row, board, selected):
        manifest = row['manifest']
        applicable = (board['version_id'] == row['storyboard_version_id']
            and board['version'] == board['current_version'] and board['confirmation_effective'])
        return {'id': row['id'], 'idempotency_key': row['idempotency_key'], 'status': row['status'],
            'version': manifest['version'], 'shot_key': row['shot_key'], 'frame_role': row['frame_role'],
            'kind': row['kind'], 'prompt': manifest['prompt'], 'size': manifest['size'],
            'manifest': manifest, 'media_id': row['media_id'],
            'media_url': f'/api/production/projects/{row["project_id"]}/media/{row["media_id"]}' if row['media_id'] else None,
            'applicable': bool(applicable), 'selected': selected.get(self._slot(row)) == row['id'],
            'error_code': row['error_code'], 'error': ERRORS.get(row['error_code'], ''),
            'created_at': row['created_at'].isoformat(),
            'started_at': row['started_at'].isoformat() if row['started_at'] else None,
            'finished_at': row['finished_at'].isoformat() if row['finished_at'] else None}

    def list(self, project, series, version=None):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            board = self.store._read(conn, project, series, version)
            r, b = tables['media_runs'], domain['storyboard_versions']
            rows = conn.execute(sa.select(r).join(b, sa.and_(b.c.id == r.c.storyboard_version_id,
                b.c.project_id == r.c.project_id)).where(r.c.project_id == project,
                b.c.breakdown_version_id == series).order_by(r.c.created_at.desc(), r.c.id)).mappings().all()
            selected = self._selected(conn, project)
            return {'runs': [self._serialize(conn, row, board, selected) for row in rows],
                    'selections': list(selected.values()), 'max_runs': MAX_MEDIA_RUNS}

    def prompt(self, project, series, version, shot_key, role):
        with self.store.engine.begin() as conn:
            board = self.store._read(conn, project, series, version)
        try:
            return build_frame_prompt(board['content'], shot_key, role)
        except ValueError as exc:
            raise InvalidProduction(str(exc)) from None

    def video_input(self, project, series, version, shot_key):
        from app.production.video_input import build_video_input
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            board = self._board(conn, project, series, version)
            identity = self._selected(conn, project).get((board['version_id'], shot_key, 'first'))
            if identity is None:
                raise ProductionConflict('请先选用当前镜头、当前版本的首帧图片')
            selected = dict(self._run(conn, project, series, identity)) | {'selected': True}
            try:
                packet = build_video_input(board, shot_key, selected)
            except ValueError as exc:
                raise InvalidProduction(str(exc)) from None
            packet['first_frame']['url'] = f'/api/production/projects/{project}/media/{selected["media_id"]}'
            packet['executable'] = False
            packet['status'] = 'provider_not_configured'
            return packet

    def create(self, project, series, request):
        t = tables['media_runs']
        fingerprint = digest({'storyboard_id': series, **request.model_dump(mode='json')})
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            existing = conn.execute(sa.select(t).where(t.c.project_id == project,
                t.c.idempotency_key == request.idempotency_key)).mappings().first()
            if existing:
                if existing['request_sha256'] != fingerprint:
                    raise ProductionConflict('幂等键已用于不同图片请求，请刷新记录')
                board = self.store._read(conn, project, series)
                return self._serialize(conn, existing, board, self._selected(conn, project))
            board = self._board(conn, project, series, request.expected_version)
            profile = self.store._profile(conn, request.profile.profile_id, request.profile.version)
            config = ModelConfig.model_validate(profile['config'])
            if config.adapter not in ('openai_images', 'ark_seedream') or config.purpose != 'image' or config.reasoning_protocol != 'none':
                raise InvalidProduction('请选择兼容图片接口或火山 Seedream 图片配置，不使用文本思考参数')
            if any(value is not None for value in config.parameters.model_dump().values()):
                raise InvalidProduction('图片适配器不接受文本生成参数，请使用独立图片配置')
            if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project)).scalar_one() >= MAX_MEDIA_RUNS:
                raise ProductionConflict('已达到项目累计100次图片请求上限，失败和取消保留记录')
            if conn.execute(sa.select(t.c.id).where(t.c.project_id == project,
                t.c.storyboard_version_id == board['version_id'], t.c.shot_key == request.shot_key,
                t.c.frame_role == request.frame_role, t.c.status.in_(['queued', 'running']))).first():
                raise ProductionConflict('同一镜头帧已有待处理任务，请先刷新记录')
            try:
                packet = build_frame_prompt(board['content'], request.shot_key, request.frame_role, request.prompt)
            except ValueError as exc:
                raise InvalidProduction(str(exc)) from None
            if config.adapter == 'ark_seedream':
                from app.production.ark import ArkImageAdapter
                try:
                    ArkImageAdapter.validate_input(config, packet['prompt'], request.size)
                except PlannerError as exc:
                    raise InvalidProduction(str(exc)) from None
            shots = domain['shots']
            shot = conn.execute(sa.select(shots.c.id).where(shots.c.project_id == project,
                shots.c.storyboard_version_id == board['version_id'],
                shots.c.content['key'].astext == request.shot_key)).scalar_one()
            identity = uuid4().hex
            manifest = packet['manifest'] | {'storyboard_id': series, 'version': board['version'],
                'source_version_id': board['source_version_id'], 'board_sha256': digest(board['content']),
                'prompt': packet['prompt'], 'size': request.size, 'profile': request.profile.model_dump(),
                'adapter': config.adapter, 'model': config.model, 'reference_images': []}
            conn.execute(t.insert().values(id=identity, project_id=project, storyboard_version_id=board['version_id'],
                shot_id=shot, shot_key=request.shot_key, frame_role=request.frame_role, kind='image',
                profile_id=request.profile.profile_id, profile_version=request.profile.version,
                idempotency_key=request.idempotency_key, request_sha256=fingerprint, manifest=manifest, status='queued'))
            return self._serialize(conn, self._run(conn, project, series, identity), board, self._selected(conn, project))

    def select(self, project, series, identity, expected_version):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._run(conn, project, series, identity)
            board = self._board(conn, project, series, expected_version)
            if row['status'] != 'succeeded' or row['storyboard_version_id'] != board['version_id']:
                raise ProductionConflict('仅能选用当前分镜版本的成功图片')
            if self._selected(conn, project).get(self._slot(row)) != identity:
                conn.execute(tables['media_selections'].insert().values(project_id=project, run_id=identity))
            return self._serialize(conn, row, board, self._selected(conn, project))

    def _stop(self, project, series, identity, source, target):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._run(conn, project, series, identity)
            if row['status'] == source:
                changed = conn.execute(tables['media_runs'].update().where(tables['media_runs'].c.id == identity,
                    tables['media_runs'].c.status == source).values(status=target, finished_at=sa.func.now(),
                    error_code='interrupted' if target == 'unknown' else None).returning(tables['media_runs'].c.id)).scalar_one_or_none()
                if changed is None:
                    raise ProductionConflict('任务状态已变化，请刷新记录')
            elif row['status'] != target:
                raise ProductionConflict('任务状态已变化，请刷新记录')
            return self._serialize(conn, self._run(conn, project, series, identity),
                self.store._read(conn, project, series), self._selected(conn, project))

    def cancel(self, project, series, identity):
        return self._stop(project, series, identity, 'queued', 'cancelled')

    def abandon(self, project, series, identity):
        return self._stop(project, series, identity, 'running', 'unknown')

    def media(self, project, identity):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project)
            m = domain['media_files']
            row = conn.execute(sa.select(m).where(m.c.id == identity, m.c.project_id == project)).mappings().first()
            if row is None:
                raise KeyError(identity)
            path = self.files.path(row['storage_key'])
            if not path.is_file():
                raise KeyError(identity)
            return path, row['media_type']

    def run_once(self, adapter=None):
        t = tables['media_runs']
        with self.store.engine.begin() as conn:
            row = conn.execute(sa.select(t).where(t.c.status == 'queued')
                .order_by(t.c.created_at, t.c.id).with_for_update(skip_locked=True).limit(1)).mappings().first()
            if row is None:
                return False
            row = dict(row)
            conn.execute(t.update().where(t.c.id == row['id']).values(status='running', started_at=sa.func.now()))
        error, saved = None, None
        try:
            with self.store.engine.begin() as conn:
                self.store._project(conn, row['project_id'], lock=True)
                if conn.execute(sa.select(t.c.status).where(t.c.id == row['id'])).scalar_one() != 'running':
                    return True
                self._board(conn, row['project_id'], row['manifest']['storyboard_id'], row['manifest']['version'])
                config = ModelConfig.model_validate(self.store._profile(conn, row['profile_id'], row['profile_version'])['config'])
            if adapter is None and config.adapter == 'ark_seedream':
                from app.production.ark import ArkImageAdapter
                adapter = ArkImageAdapter()
            result = (adapter or ImageAdapter()).generate(config, row['manifest']['prompt'], row['manifest']['size'])
            saved = self.files.put(result.data, result.mime_type)
        except ProductionConflict:
            error = 'source_changed'
        except PlannerError as exc:
            error = exc.code if exc.code in ERRORS else 'provider_error'
        except OSError:
            error = 'storage_error'
        except Exception:
            # Unknown failures after claiming must not silently requeue a possibly billed call.
            error = 'internal_error'
        with self.store.engine.begin() as conn:
            self.store._project(conn, row['project_id'], lock=True)
            active = conn.execute(sa.select(t.c.status).where(t.c.id == row['id']).with_for_update()).scalar_one()
            if active != 'running':
                return True
            media_id = None
            if saved is not None and error is None:
                media_id = uuid4().hex
                conn.execute(domain['media_files'].insert().values(id=media_id, project_id=row['project_id'],
                    storage_key=saved['storage_key'], media_type=saved['mime_type'], checksum=saved['checksum'],
                    size_bytes=saved['size_bytes'], metadata=saved['metadata']))
                conn.execute(domain['shot_media_links'].insert().values(id=uuid4().hex, project_id=row['project_id'],
                    shot_id=row['shot_id'], media_file_id=media_id, role=row['frame_role']))
            status = ('unknown' if error in ('outcome_unknown', 'storage_error', 'internal_error') else 'failed') if error else 'succeeded'
            conn.execute(t.update().where(t.c.id == row['id']).values(status=status, error_code=error,
                media_id=media_id, finished_at=sa.func.now()))
        return True
