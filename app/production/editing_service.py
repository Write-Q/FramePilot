"""Durable local postproduction. Rendering runs outside database transactions."""
import hashlib
import io
import math
import os
from pathlib import Path
import re
import wave
from uuid import uuid4

import av
import sqlalchemy as sa

from app.models import production_tables as tables
from app.production.editing_contracts import AcceptRequest, ExportRequest, TimelineContent, TimelineRequest
from app.production.planning import digest
from app.production.store import InvalidProduction, ProductionConflict
from app.production.video_files import VideoFiles
from app.production.video_runtime import VideoRuntime

MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_ASSETS = 100
MAX_EXPORTS = 100
ERRORS = {
    'source_changed': '分镜、已选视频或时间线已变化，本次未导出。',
    'input_unavailable': '固定素材文件缺失或校验失败，本次未导出。',
    'render_failed': '本地渲染失败，请检查媒体、FFmpeg和字体配置后新建导出。',
    'invalid_output': '成片未通过实际视频解码校验。',
    'interrupted': '已人工标记结果未知；晚到结果不会覆盖记录，不会自动重新渲染。',
}


class EditingService:
    def __init__(self, store, files=None, audio_root=None):
        self.store = store
        self.files = files if files is not None else VideoFiles()
        self.audio_root = Path(audio_root or os.getenv('FRAMEPILOT_AUDIO_ROOT') or
            Path(__file__).resolve().parents[2] / 'data' / 'audio').resolve()
        self.video = VideoRuntime(store, files=self.files)

    def _audio_path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}\.wav', key):
            raise ValueError('非法音频标识')
        path = (self.audio_root / key).resolve()
        if path.parent != self.audio_root:
            raise ValueError('音频路径越界')
        return path

    def _verify_audio(self, output):
        path = self._audio_path(output['storage_key'])
        if not 0 < output['size_bytes'] <= MAX_AUDIO_BYTES or path.stat().st_size != output['size_bytes']:
            raise ValueError('音频大小已变化')
        with path.open('rb') as source:
            checksum = hashlib.file_digest(source, 'sha256').hexdigest()
        if checksum != output['checksum']:
            raise ValueError('音频校验失败')
        return path

    def _audio(self, conn, project, series, identity):
        t = tables['editing_audio']
        row = conn.execute(sa.select(t).where(t.c.id == identity,
            t.c.project_id == project, t.c.storyboard_id == series)).mappings().first()
        if row is None:
            raise KeyError(identity)
        return row

    def _export(self, conn, project, series, identity):
        t = tables['editing_exports']
        row = conn.execute(sa.select(t).where(t.c.id == identity,
            t.c.project_id == project, t.c.storyboard_id == series)).mappings().first()
        if row is None:
            raise KeyError(identity)
        return row

    def _timeline(self, conn, project, series, version=None):
        t = tables['editing_timelines']
        query = sa.select(t).where(t.c.project_id == project, t.c.storyboard_id == series)
        if version is not None:
            query = query.where(t.c.version_no == version)
        return conn.execute(query.order_by(t.c.version_no.desc()).limit(1)).mappings().first()

    def _board(self, conn, project, series, version):
        board = self.store._read(conn, project, series, version)
        if board['version'] != board['current_version'] or not board['confirmation_effective'] or not board['source_current']:
            raise ProductionConflict('需要当前已确认分镜和来源剧本版本')
        return board

    def _manifest(self, conn, project, series, board, content):
        selected = self.video._selected(conn, project)
        clips, audio = [], []
        for clip in content.clips:
            try:
                row = self.video._run(conn, project, series, clip.run_id)
            except KeyError:
                raise InvalidProduction('视频不属于当前项目和分镜') from None
            if (row['status'] != 'succeeded' or row['storyboard_version_id'] != board['version_id'] or
                    selected.get((board['version_id'], row['shot_key'])) != row['id']):
                raise ProductionConflict('仅能使用当前已确认版本已选用的成功视频')
            output = row['output']
            if not output or clip.end_ms > output['metadata']['duration_ms']:
                raise InvalidProduction('裁切区间超过实际视频时长')
            try:
                self.files.verify(output)
            except (OSError, ValueError, KeyError):
                raise InvalidProduction('视频素材文件不可读取或校验失败') from None
            clips.append({'run_id': row['id'], 'shot_key': row['shot_key'], 'output': output})
        for track in content.audio_tracks:
            try:
                row = self._audio(conn, project, series, track.asset_id)
                self._verify_audio(row['output'])
            except (KeyError, OSError, ValueError):
                raise InvalidProduction('音频不属于当前项目分镜或文件校验失败') from None
            audio.append({'asset_id': row['id'], 'output': row['output'], 'duration_ms': row['duration_ms']})
        return {'storyboard_id': series, 'storyboard_version_id': board['version_id'],
            'source_version': board['version'], 'source_version_id': board['source_version_id'],
            'board_sha256': digest(board['content']), 'clips': clips, 'audio': audio,
            'duration_ms': sum(c.end_ms - c.start_ms for c in content.clips)}

    def _applicable(self, conn, row, board):
        manifest = row['manifest']
        if (row['storyboard_version_id'] != board['version_id'] or
                board['version'] != board['current_version'] or not board['confirmation_effective'] or not board['source_current'] or
                manifest['board_sha256'] != digest(board['content'])):
            return False
        selected = self.video._selected(conn, row['project_id'])
        return all(selected.get((row['storyboard_version_id'], clip['shot_key'])) == clip['run_id']
                   for clip in manifest['clips'])

    def _serialize_timeline(self, conn, row, board):
        return {'id': row['id'], 'version': row['version_no'], 'source_version': row['source_version'],
            'content': row['content'], 'manifest': row['manifest'],
            'applicable': bool(self._applicable(conn, row, board)), 'created_at': row['created_at'].isoformat()}

    @staticmethod
    def _serialize_audio(row):
        return {'id': row['id'], 'duration_ms': row['duration_ms'], 'output': row['output'],
            'media_url': f'/api/production/projects/{row["project_id"]}/storyboards/{row["storyboard_id"]}/editing/audio/{row["id"]}/media',
            'created_at': row['created_at'].isoformat()}

    def _serialize_export(self, conn, row):
        a = tables['editing_acceptances']
        accepted = conn.execute(sa.select(a).where(a.c.project_id == row['project_id'], a.c.export_id == row['id'])).mappings().first()
        base = f'/api/production/projects/{row["project_id"]}/storyboards/{row["storyboard_id"]}/editing/exports/{row["id"]}'
        return {'id': row['id'], 'status': row['status'], 'timeline_id': row['timeline_id'],
            'version': row['manifest']['timeline_version'], 'manifest': row['manifest'], 'output': row['output'],
            'idempotency_key': row['idempotency_key'], 'error_code': row['error_code'],
            'error': ERRORS.get(row['error_code'], ''), 'media_url': base + '/media' if row['status'] == 'succeeded' else None,
            'download_url': base + '/download' if row['status'] == 'succeeded' else None,
            'accepted': accepted is not None,
            'acceptance': {'comment': accepted['comment'], 'created_at': accepted['created_at'].isoformat()} if accepted else None,
            **{key: row[key].isoformat() if row[key] else None for key in ('created_at', 'started_at', 'finished_at')}}

    def _exports(self, conn, project, series):
        t = tables['editing_exports']
        rows = conn.execute(sa.select(t).where(t.c.project_id == project, t.c.storyboard_id == series)
            .order_by(t.c.created_at.desc(), t.c.id)).mappings()
        return [self._serialize_export(conn, row) for row in rows]

    def list(self, project, series, version=None):
        with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn, conn.begin():
            board = self.store._read(conn, project, series)
            row = self._timeline(conn, project, series, version)
            if row is None and version is not None:
                raise KeyError(version)
            t, a = tables['editing_timelines'], tables['editing_audio']
            versions = conn.execute(sa.select(t).where(t.c.project_id == project, t.c.storyboard_id == series)
                .order_by(t.c.version_no.desc())).mappings().all()
            audio = conn.execute(sa.select(a).where(a.c.project_id == project, a.c.storyboard_id == series)
                .order_by(a.c.created_at, a.c.id)).mappings().all()
            selected = self.video._selected(conn, project)
            selected_clips = []
            for shot in board['content']['shots']:
                identity = selected.get((board['version_id'], shot['key']))
                if identity:
                    video = self.video._run(conn, project, series, identity)
                    if video['status'] == 'succeeded':
                        selected_clips.append({'run_id': video['id'], 'shot_key': video['shot_key'],
                            'duration_ms': video['output']['metadata']['duration_ms'],
                            'media_url': f'/api/production/projects/{project}/storyboards/{series}/video-runs/{video["id"]}/media',
                            'output': video['output']})
            return {'timeline': self._serialize_timeline(conn, row, board) if row else None,
                'versions': [self._serialize_timeline(conn, item, board) for item in versions],
                'exports': self._exports(conn, project, series), 'audio': [self._serialize_audio(item) for item in audio],
                'source_version': board['version'], 'source_confirmed': bool(board['confirmation_effective']),
                'source_current': bool(board['source_current']), 'confirmed': bool(board['confirmation_effective']),
                'selected_clips': selected_clips}

    def save(self, project, series, request):
        request = TimelineRequest.model_validate(request)
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            board = self._board(conn, project, series, request.source_version)
            current = self._timeline(conn, project, series)
            if (current['version_no'] if current else 0) != request.expected_version:
                raise ProductionConflict('时间线已更新，请刷新后提交')
            manifest = self._manifest(conn, project, series, board, request.content)
            identity = uuid4().hex
            conn.execute(tables['editing_timelines'].insert().values(id=identity, project_id=project,
                storyboard_id=series, storyboard_version_id=board['version_id'], version_no=request.expected_version + 1,
                source_version=request.source_version, content=request.content.model_dump(mode='json'), manifest=manifest))
            return self._serialize_timeline(conn, self._timeline(conn, project, series), board)

    def upload_audio(self, project, series, data, mime='audio/wav'):
        if mime not in ('audio/wav', 'audio/x-wav', 'audio/wave') or not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO_BYTES:
            raise InvalidProduction('仅接收20MiB以内WAV音频')
        try:
            # Check actual RIFF/WAVE structure before the decoder; a filename is never trusted.
            with wave.open(io.BytesIO(data), 'rb') as source:
                frames, rate = source.getnframes(), source.getframerate()
                if not 0 < frames <= 600 * rate:
                    raise ValueError()
            samples = 0
            with av.open(io.BytesIO(data), mode='r', format='wav') as container:
                if len(container.streams.audio) != 1 or len(container.streams.video):
                    raise ValueError()
                for frame in container.decode(audio=0):
                    if frame.sample_rate != rate:
                        raise ValueError()
                    samples += frame.samples
                    if samples > 600 * rate:
                        raise ValueError()
            if samples != frames:
                raise ValueError()
            duration = math.ceil(samples * 1000 / rate)
        except Exception:
            raise InvalidProduction('WAV解码失败或音频超过600秒') from None
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            self.store._read(conn, project, series)
            t = tables['editing_audio']
            if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project)).scalar_one() >= MAX_AUDIO_ASSETS:
                raise ProductionConflict('已达到项目100条音频素材上限')
            identity, key = uuid4().hex, uuid4().hex + '.wav'
            output = {'storage_key': key, 'checksum': hashlib.sha256(data).hexdigest(),
                      'size_bytes': len(data), 'mime_type': 'audio/wav'}
            self.audio_root.mkdir(parents=True, exist_ok=True)
            with self._audio_path(key).open('xb') as target:
                target.write(data)
            conn.execute(t.insert().values(id=identity, project_id=project, storyboard_id=series,
                output=output, duration_ms=duration))
            return self._serialize_audio(self._audio(conn, project, series, identity))

    def audio_media(self, project, series, identity):
        with self.store.engine.begin() as conn:
            row = self._audio(conn, project, series, identity)
            output = row['output']
        try:
            return self._verify_audio(output), 'audio/wav'
        except (OSError, ValueError):
            raise KeyError(identity) from None

    def create_export(self, project, series, request):
        request = ExportRequest.model_validate(request)
        fingerprint = digest({'storyboard_id': series, **request.model_dump(mode='json')})
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            t = tables['editing_exports']
            existing = conn.execute(sa.select(t).where(t.c.project_id == project,
                t.c.idempotency_key == request.idempotency_key)).mappings().first()
            if existing:
                if existing['request_sha256'] != fingerprint:
                    raise ProductionConflict('幂等键已用于其他导出请求')
                return self._serialize_export(conn, existing)
            board = self.store._read(conn, project, series)
            row = self._timeline(conn, project, series)
            if row is None or row['version_no'] != request.expected_version:
                raise ProductionConflict('请先保存时间线或刷新当前版本')
            if not self._applicable(conn, row, board):
                raise ProductionConflict('时间线来源或已选视频已变化，请保存新版本')
            # Recheck both asset ownership and pinned checksums before queuing.
            actual = self._manifest(conn, project, series, board, TimelineContent.model_validate(row['content']))
            if actual != row['manifest']:
                raise ProductionConflict('固定素材已变化')
            if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project)).scalar_one() >= MAX_EXPORTS:
                raise ProductionConflict('已达到项目100次导出上限')
            identity = uuid4().hex
            conn.execute(t.insert().values(id=identity, project_id=project, storyboard_id=series,
                timeline_id=row['id'], idempotency_key=request.idempotency_key, request_sha256=fingerprint,
                manifest=dict(row['manifest']) | {'timeline_id': row['id'], 'timeline_version': row['version_no'],
                    'timeline_sha256': digest(row['content'])}, status='queued'))
            return self._serialize_export(conn, self._export(conn, project, series, identity))

    def exports(self, project, series):
        with self.store.engine.begin() as conn:
            self.store._read(conn, project, series)
            return self._exports(conn, project, series)

    def media(self, project, series, identity):
        with self.store.engine.begin() as conn:
            row = self._export(conn, project, series, identity)
            if row['status'] != 'succeeded' or not row['output']:
                raise KeyError(identity)
            output = row['output']
        try:
            return self.files.verify(output), output['mime_type']
        except (OSError, ValueError):
            raise KeyError(identity) from None

    def abandon(self, project, series, identity):
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._export(conn, project, series, identity)
            if row['status'] in ('queued', 'running'):
                t = tables['editing_exports']
                conn.execute(t.update().where(t.c.id == identity, t.c.status == row['status'],
                    t.c.claim_id.is_not_distinct_from(row['claim_id'])).values(status='unknown', claim_id=None,
                    error_code='interrupted', finished_at=sa.func.now()))
            elif row['status'] != 'unknown':
                raise ProductionConflict('当前导出状态不能标记中断')
            return self._serialize_export(conn, self._export(conn, project, series, identity))

    def accept(self, project, series, identity, request=None):
        request = AcceptRequest.model_validate(request or {})
        # A human acceptance refers to a readable exact output, never auto quality scoring.
        self.media(project, series, identity)
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            row = self._export(conn, project, series, identity)
            t = tables['editing_acceptances']
            if not conn.execute(sa.select(t.c.id).where(t.c.project_id == project, t.c.export_id == identity)).first():
                conn.execute(t.insert().values(id=uuid4().hex, project_id=project, export_id=identity, comment=request.comment))
            return self._serialize_export(conn, row)

    def _preflight(self, row):
        project, series = row['project_id'], row['storyboard_id']
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            current = self._export(conn, project, series, row['id'])
            if current['status'] != 'running' or current['claim_id'] != row['claim_id']:
                return None
            board = self.store._read(conn, project, series)
            timeline = self._timeline(conn, project, series, row['manifest']['timeline_version'])
            if (timeline is None or timeline['id'] != row['timeline_id'] or
                    digest(timeline['content']) != row['manifest']['timeline_sha256'] or
                    not self._applicable(conn, timeline, board)):
                raise ProductionConflict('固定时间线来源已变化')
            content = dict(timeline['content'])
        # The files are pinned in immutable history and verified outside the transaction.
        clips = [dict(params) | {'path': self.files.verify(item['output'])}
                 for params, item in zip(content['clips'], row['manifest']['clips'], strict=True)]
        audio = [dict(params) | {'path': self._verify_audio(item['output'])}
                 for params, item in zip(content['audio_tracks'], row['manifest']['audio'], strict=True)]
        return content, clips, audio

    def run_once(self, renderer=None):
        t = tables['editing_exports']
        with self.store.engine.begin() as conn:
            row = conn.execute(sa.select(t).where(t.c.status == 'queued').order_by(t.c.created_at, t.c.id)
                .with_for_update(skip_locked=True).limit(1)).mappings().first()
            if row is None:
                return False
            row = dict(row)
            claim = uuid4().hex
            conn.execute(t.update().where(t.c.id == row['id']).values(status='running', claim_id=claim, started_at=sa.func.now()))
            row.update(status='running', claim_id=claim)
        output, error = None, None
        try:
            context = self._preflight(row)
            if context is None:
                return True
        except ProductionConflict:
            error = 'source_changed'
        except (OSError, ValueError, KeyError):
            error = 'input_unavailable'
        if error is None:
            try:
                if renderer is None:
                    from app.production.editing_render import render_timeline
                    renderer = render_timeline
                data = renderer(*context)
            except Exception:
                error = 'render_failed'
            else:
                try:
                    output = self.files.put(data, 'video/mp4')
                except Exception:
                    error = 'invalid_output'
        with self.store.engine.begin() as conn:
            conn.execute(t.update().where(t.c.id == row['id'], t.c.status == 'running', t.c.claim_id == claim)
                .values(status='failed' if error else 'succeeded', error_code=error,
                    output=output if output is not None else sa.null(),
                    claim_id=None, finished_at=sa.func.now()))
        return True
