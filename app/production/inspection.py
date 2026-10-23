"""Real sparse frame evidence and manual observations, never semantic approval."""
import hashlib
from uuid import uuid4

import sqlalchemy as sa

from app.models import production_tables as tables
from app.production.chat import PlannerError
from app.production.inspection_contracts import CreateInspection, ManualReview
from app.production.media_io import MediaFiles, MAX_IMAGE_BYTES
from app.production.planning import digest
from app.production.store import ProductionConflict
from app.production.video_runtime import VideoRuntime
from app.production.video_sampling import sample_video

MAX_INSPECTIONS = 10
MAX_NOTES = 50


class InspectionService:
    def __init__(self, store, *, runtime=None, frames=None):
        self.store = store
        self.runtime = runtime if runtime is not None else VideoRuntime(store)
        self.frames = frames if frames is not None else MediaFiles()

    def _report(self, conn, project, run_id, identity):
        t = tables['video_inspections']
        row = conn.execute(sa.select(t).where(t.c.project_id == project, t.c.run_id == run_id,
            t.c.id == identity)).mappings().first()
        if row is None:
            raise KeyError(identity)
        return row

    def _available(self, run):
        if run['status'] != 'succeeded' or not run['output']:
            raise ProductionConflict('仅能审核成功且已验证的视频')
        try:
            return self.runtime.files.verify(run['output'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise ProductionConflict('视频文件缺失或校验失败，请恢复原视频后重新操作') from None

    def _eligible(self, conn, project, series, run, version=None):
        board = self.store._read(conn, project, series)
        if (board['version_id'] != run['storyboard_version_id']
                or not board['confirmation_effective']
                or (version is not None and board['version'] != version)
                or board['source_version_id'] != run['manifest']['source_version_id']
                or digest(board['content']) != run['manifest']['board_sha256']):
            raise ProductionConflict('需要视频对应的当前已确认分镜和来源；旧报告仅供查看')
        self._available(run)
        return board

    def _serialize(self, conn, row, run, board):
        stale = []
        if board['version_id'] != row['storyboard_version_id']:
            stale.append('board_changed')
        if not board['confirmation_effective'] or board['source_version_id'] != row['manifest']['source_version_id']:
            stale.append('source_changed')
        if run['output'] is None or run['output'].get('checksum') != row['video_checksum']:
            stale.append('video_changed')
        try:
            self._available(run)
        except ProductionConflict:
            stale.append('video_unavailable')
        t = tables['video_inspection_notes']
        notes = conn.execute(sa.select(t).where(t.c.project_id == row['project_id'],
            t.c.inspection_id == row['id']).order_by(t.c.id)).mappings().all()
        base = (f'/api/production/projects/{row["project_id"]}/storyboards/{row["manifest"]["storyboard_id"]}'
                f'/video-runs/{row["run_id"]}/inspections/{row["id"]}/frames')
        return {'id': row['id'], 'run_id': row['run_id'], 'version': row['manifest']['version'],
            'video_checksum': row['video_checksum'], 'idempotency_key': row['idempotency_key'],
            'applicable': not stale, 'stale_reasons': stale, 'technical': row['technical'],
            'frames': [{'at_ms': item['at_ms'], 'url': f'{base}/{index}'} for index, item in enumerate(row['frames'])],
            'notes': [{**{key: item[key] for key in ('id', 'decision', 'findings', 'comment', 'expected_version', 'idempotency_key')},
                'created_at': item['created_at'].isoformat()} for item in notes],
            'content_status': notes[-1]['decision'] if notes else 'pending',
            'created_at': row['created_at'].isoformat(), 'max_notes': MAX_NOTES}

    def _existing(self, conn, project, key, fingerprint, table):
        row = conn.execute(sa.select(table).where(table.c.project_id == project,
            table.c.idempotency_key == key)).mappings().first()
        if row is not None and row['request_sha256'] != fingerprint:
            raise ProductionConflict('幂等键已用于不同审核参数，请刷新后明确发起新请求')
        return row

    def _budget(self, conn, project, run_id):
        t = tables['video_inspections']
        if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project,
                t.c.run_id == run_id)).scalar_one() >= MAX_INSPECTIONS:
            raise ProductionConflict('已达到此视频累计十份审核报告上限')

    def create(self, project, series, run_id, request):
        request = CreateInspection.model_validate(request)
        fingerprint = digest({'storyboard_id': series, 'run_id': run_id, **request.model_dump(mode='json')})
        t = tables['video_inspections']
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            run = dict(self.runtime._run(conn, project, series, run_id))
            existing = self._existing(conn, project, request.idempotency_key, fingerprint, t)
            if existing is not None:
                return self._serialize(conn, existing, run, self.store._read(conn, project, series))
            board = self._eligible(conn, project, series, run)
            self._budget(conn, project, run_id)
        # Decode and store JPEGs outside DB transactions. No model/provider request is involved.
        saved_frames = []
        retained = False
        try:
            path = self._available(run)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != run['output']['checksum']:
                raise ValueError('changed video')
            samples = sample_video(data, run['output']['mime_type'], request.count)
            actual = {key: run['output']['metadata'][key] for key in ('width', 'height', 'duration_ms')}
            for sample in samples:
                if not 0 <= sample['at_ms'] < actual['duration_ms']:
                    raise ValueError('sample outside duration')
                saved_frames.append({'at_ms': sample['at_ms'], **self.frames.put(sample['data'], 'image/jpeg')})
            planned = {'duration_ms': run['manifest']['packet']['duration_ms'],
                       'aspect_ratio': board['content']['aspect_ratio']}
            warnings = []
            if abs(actual['duration_ms'] - planned['duration_ms']) > max(100, planned['duration_ms'] * .05):
                warnings.append('duration_mismatch')
            width, height = map(int, planned['aspect_ratio'].split(':'))
            if abs(actual['width'] / actual['height'] - width / height) / (width / height) > .02:
                warnings.append('aspect_ratio_mismatch')
            technical = {'actual': actual, 'planned': planned, 'warnings': warnings,
                'validation': 'decoded_video', 'sampling': 'sparse_frames',
                'semantic_review': 'not_configured', 'audio_review': 'not_performed'}
            with self.store.engine.begin() as conn:
                self.store._project(conn, project, lock=True)
                current = self.runtime._run(conn, project, series, run_id)
                existing = self._existing(conn, project, request.idempotency_key, fingerprint, t)
                if existing is not None:
                    return self._serialize(conn, existing, current, self.store._read(conn, project, series))
                board = self._eligible(conn, project, series, current)
                if current['output']['checksum'] != run['output']['checksum']:
                    raise ProductionConflict('视频内容已变化，请刷新后重新审核')
                self._budget(conn, project, run_id)
                identity = uuid4().hex
                conn.execute(t.insert().values(id=identity, project_id=project, run_id=run_id,
                    storyboard_version_id=run['storyboard_version_id'], video_checksum=run['output']['checksum'],
                    idempotency_key=request.idempotency_key, request_sha256=fingerprint,
                    manifest={'storyboard_id': series, 'version': board['version'],
                        'source_version_id': board['source_version_id'], 'board_sha256': digest(board['content'])},
                    technical=technical, frames=saved_frames))
                result = self._serialize(conn, self._report(conn, project, run_id, identity), current, board)
            retained = True
            return result
        except (OSError, ValueError, KeyError, TypeError, PlannerError) as exc:
            # Do not expose decoder diagnostics, local paths or storage exception details.
            if isinstance(exc, ProductionConflict):
                raise
            raise ProductionConflict('视频抽帧或证据保存失败，请核对原视频后重试') from None
        finally:
            if not retained:
                for item in saved_frames:
                    try:
                        self.frames.path(item['storage_key']).unlink(missing_ok=True)
                    except (OSError, ValueError):
                        pass

    def list(self, project, series, run_id):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            run = self.runtime._run(conn, project, series, run_id)
            board = self.store._read(conn, project, series)
            t = tables['video_inspections']
            rows = conn.execute(sa.select(t).where(t.c.project_id == project,
                t.c.run_id == run_id).order_by(t.c.created_at.desc(), t.c.id)).mappings().all()
            return {'reports': [self._serialize(conn, row, run, board) for row in rows], 'max_reports': MAX_INSPECTIONS}

    def frame(self, project, series, run_id, inspection_id, index):
        with self.store.engine.begin() as conn:
            self.runtime._run(conn, project, series, run_id)
            report = self._report(conn, project, run_id, inspection_id)
            if type(index) is not int or not 0 <= index < len(report['frames']):
                raise KeyError(index)
            item = report['frames'][index]
        try:
            path = self.frames.path(item['storage_key'])
            with path.open('rb') as source:
                data = source.read(MAX_IMAGE_BYTES + 1)
            if len(data) != item['size_bytes'] or hashlib.sha256(data).hexdigest() != item['checksum']:
                raise ValueError()
            return path, item['mime_type']
        except (OSError, ValueError, KeyError, TypeError):
            raise KeyError(index) from None

    def note(self, project, series, run_id, inspection_id, request):
        request = ManualReview.model_validate(request)
        fingerprint = digest({'storyboard_id': series, 'run_id': run_id,
            'inspection_id': inspection_id, **request.model_dump(mode='json')})
        t = tables['video_inspection_notes']
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            run = self.runtime._run(conn, project, series, run_id)
            report = self._report(conn, project, run_id, inspection_id)
            existing = self._existing(conn, project, request.idempotency_key, fingerprint, t)
            if existing is not None:
                return self._serialize(conn, report, run, self.store._read(conn, project, series))
            board = self._eligible(conn, project, series, run, request.expected_version)
            if report['video_checksum'] != run['output']['checksum'] or report['storyboard_version_id'] != board['version_id']:
                raise ProductionConflict('审核报告对应的版本或视频已变化')
            duration = report['technical']['actual']['duration_ms']
            if any(finding.start_ms >= duration or finding.end_ms > duration for finding in request.findings):
                raise ProductionConflict('问题时间范围必须位于实际视频时长内')
            if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project,
                    t.c.inspection_id == inspection_id)).scalar_one() >= MAX_NOTES:
                raise ProductionConflict('已达到此报告累计五十条人工记录上限')
            conn.execute(t.insert().values(project_id=project, run_id=run_id, inspection_id=inspection_id,
                idempotency_key=request.idempotency_key, request_sha256=fingerprint,
                expected_version=request.expected_version, decision=request.decision,
                findings=[item.model_dump(mode='json') for item in request.findings], comment=request.comment))
            return self._serialize(conn, report, run, board)
