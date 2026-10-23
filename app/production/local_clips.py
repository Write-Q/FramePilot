"""Bounded local uploads with immutable source pins and retry-safe identity."""
import hashlib
import re
import unicodedata
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator
import sqlalchemy as sa

from app.models import production_tables as tables
from app.production.contracts import Contract
from app.production.planning import digest
from app.production.store import InvalidProduction, ProductionConflict
from app.production.video_files import MAX_VIDEO_BYTES, VideoFiles

MAX_LOCAL_CLIPS = 100


class LocalClipRequest(Contract):
    expected_version: int = Field(ge=1, le=2147483647, strict=True)
    filename: str = Field(min_length=1, max_length=180)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    mime: Literal['video/mp4', 'video/webm']

    @field_validator('filename', mode='before')
    @classmethod
    def display_name(cls, value):
        if not isinstance(value, str) or len(value) > 180:
            raise ValueError('文件名必须在180字以内')
        # Metadata only: never use the display name in a path or shell command.
        return ''.join(c for c in re.split(r'[/\\]', value)[-1]
                       if not unicodedata.category(c).startswith('C')).strip()


class LocalClips:
    def __init__(self, store, files=None):
        self.store = store
        self.files = files if files is not None else VideoFiles()

    def _board(self, conn, project, series, version):
        board = self.store._read(conn, project, series)
        if (board['version'] != version or board['version'] != board['current_version'] or not board['confirmation_effective']
                or not board['source_current']):
            raise ProductionConflict('需要当前已确认分镜和来源剧本版本')
        return board

    def get_owned(self, conn, project, series, identity):
        t = tables['local_clips']
        row = conn.execute(sa.select(t).where(t.c.id == identity,
            t.c.project_id == project, t.c.storyboard_id == series)).mappings().first()
        if row is None:
            raise KeyError(identity)
        return row

    @staticmethod
    def _applicable(row, board):
        return bool(row['storyboard_version_id'] == board['version_id']
            and board['version'] == board['current_version'] and board['confirmation_effective']
            and board['source_current'])

    def _serialize(self, row, board):
        return {'id': row['id'], 'run_id': row['id'], 'filename': row['filename'],
            'shot_key': row['filename'], 'version': row['version_no'], 'source': 'local_upload',
            'applicable': self._applicable(row, board), 'output': row['output'],
            'duration_ms': row['output']['metadata']['duration_ms'],
            'media_url': f'/api/production/projects/{row["project_id"]}/storyboards/{row["storyboard_id"]}/editing/local-clips/{row["id"]}/media',
            'created_at': row['created_at'].isoformat()}

    def list(self, project, series, *, conn=None, board=None):
        if conn is None:
            with self.store.engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection, connection.begin():
                return self.list(project, series, conn=connection)
        board = board if board is not None else self.store._read(conn, project, series)
        t = tables['local_clips']
        rows = conn.execute(sa.select(t).where(t.c.project_id == project, t.c.storyboard_id == series)
            .order_by(t.c.created_at, t.c.id)).mappings()
        return [self._serialize(row, board) for row in rows]

    def _existing(self, conn, project, key, fingerprint):
        t = tables['local_clips']
        row = conn.execute(sa.select(t).where(t.c.project_id == project,
            t.c.idempotency_key == key)).mappings().first()
        if row is not None and row['request_sha256'] != fingerprint:
            raise ProductionConflict('幂等键已用于其他本地素材请求')
        return row

    @staticmethod
    def _limit(conn, project):
        t = tables['local_clips']
        if conn.execute(sa.select(sa.func.count()).select_from(t).where(t.c.project_id == project)).scalar_one() >= MAX_LOCAL_CLIPS:
            raise ProductionConflict('已达到项目100条本地视频素材上限')

    def upload(self, project, series, data, mime, expected_version, filename, idempotency_key):
        try:
            request = LocalClipRequest.model_validate({'expected_version': expected_version,
                'filename': filename, 'idempotency_key': idempotency_key, 'mime': mime})
        except ValidationError:
            raise InvalidProduction('本地素材上传参数无效，请检查版本、文件名、类型和幂等键') from None
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_VIDEO_BYTES:
            raise InvalidProduction('仅接收256MiB以内非空视频')
        fingerprint = digest({'sha256': hashlib.sha256(data).hexdigest(), 'storyboard_id': series,
            **request.model_dump(mode='json')})
        with self.store.engine.begin() as conn:
            self.store._project(conn, project, lock=True)
            existing = self._existing(conn, project, request.idempotency_key, fingerprint)
            if existing is not None:
                return self._serialize(existing, self.store._read(conn, project, series))
            self._board(conn, project, series, request.expected_version)
            self._limit(conn, project)
        try:
            output = self.files.put(data, request.mime)
        except (ValueError, OSError):
            raise InvalidProduction('视频解码失败，仅支持600秒以内H.264 MP4或VP8/VP9 WebM') from None
        retained = False
        try:
            if not 0 < output['metadata']['duration_ms'] <= 600000:
                raise InvalidProduction('本地视频时长不能超过600秒')
            with self.store.engine.begin() as conn:
                self.store._project(conn, project, lock=True)
                existing = self._existing(conn, project, request.idempotency_key, fingerprint)
                if existing is not None:
                    return self._serialize(existing, self.store._read(conn, project, series))
                board = self._board(conn, project, series, request.expected_version)
                self._limit(conn, project)
                identity = 'local_' + uuid4().hex
                conn.execute(tables['local_clips'].insert().values(id=identity, project_id=project,
                    storyboard_id=series, storyboard_version_id=board['version_id'], version_no=board['version'],
                    filename=request.filename, idempotency_key=request.idempotency_key,
                    request_sha256=fingerprint, output=output))
                result = self._serialize(self.get_owned(conn, project, series, identity), board)
            retained = True
            return result
        finally:
            if not retained:
                try:
                    self.files.path(output['storage_key']).unlink(missing_ok=True)
                except OSError:
                    pass

    def media(self, project, series, identity):
        with self.store.engine.begin() as conn:
            output = self.get_owned(conn, project, series, identity)['output']
        try:
            return self.files.verify(output), output['mime_type']
        except (OSError, ValueError, KeyError):
            raise KeyError(identity) from None
