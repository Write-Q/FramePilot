"""Validated immutable local video files, with bounded decoder subprocess."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

MAX_VIDEO_BYTES = 256 * 1024 * 1024


class VideoFiles:
    validated_video = True

    def __init__(self, root=None):
        self.root = Path(root or os.getenv('FRAMEPILOT_VIDEO_ROOT') or Path(__file__).resolve().parents[2] / 'data' / 'video').resolve()

    def path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}\.(mp4|webm)', key):
            raise ValueError('非法视频存储标识')
        target = (self.root / key).resolve()
        if target.parent != self.root:
            raise ValueError('视频路径越界')
        return target

    def put(self, data, mime):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_VIDEO_BYTES or mime not in ('video/mp4', 'video/webm'):
            raise ValueError('视频类型或大小无效')
        try:
            result = subprocess.run([sys.executable, '-m', 'app.production.video_probe', mime],
                input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                cwd=Path(__file__).resolve().parents[2], check=True)
            if len(result.stdout) > 2000:
                raise ValueError()
            metadata = json.loads(result.stdout)
            if set(metadata) != {'width', 'height', 'duration_ms'} or any(type(v) is not int or v <= 0 for v in metadata.values()):
                raise ValueError()
        except (subprocess.SubprocessError, ValueError, OSError, TypeError):
            raise ValueError('视频解码、尺寸或处理时限校验失败') from None
        self.root.mkdir(parents=True, exist_ok=True)
        key = uuid4().hex + ('.mp4' if mime == 'video/mp4' else '.webm')
        path, created = self.path(key), False
        try:
            with path.open('xb') as output:
                created = True
                output.write(data)
        except BaseException:
            # Only this attempt's new file may be removed. In particular, an
            # exclusive-create collision must never remove existing media.
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return {'storage_key': key, 'checksum': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
                'mime_type': mime, 'metadata': metadata}

    def verify(self, output):
        path = self.path(output['storage_key'])
        if not 0 < output['size_bytes'] <= MAX_VIDEO_BYTES or path.stat().st_size != output['size_bytes']:
            raise ValueError('视频文件大小已变化')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != output['checksum']:
            raise ValueError('视频文件校验失败')
        return path
