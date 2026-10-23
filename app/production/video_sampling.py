"""Bounded real-frame evidence; sparse samples are not semantic approval."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys

from app.production.video_files import MAX_VIDEO_BYTES


def sample_video(data, mime, count=8):
    if type(count) is not int or not 1 <= count <= 12 or not isinstance(data, bytes) or not 0 < len(data) <= MAX_VIDEO_BYTES:
        raise ValueError('视频或采样数量无效')
    if mime not in ('video/mp4', 'video/webm'):
        raise ValueError('视频格式不支持')
    try:
        result = subprocess.run([sys.executable, '-m', 'app.production.video_sampling', mime, str(count)],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=True,
            cwd=Path(__file__).resolve().parents[2])
        if len(result.stdout) > 12_000_000:
            raise ValueError()
        raw = json.loads(result.stdout)
        if not isinstance(raw, list) or not 1 <= len(raw) <= count:
            raise ValueError()
        samples = []
        for item in raw:
            if type(item['at_ms']) is not int or not 0 <= item['at_ms'] <= 600000:
                raise ValueError()
            image = base64.b64decode(item['jpeg'], validate=True)
            if not 0 < len(image) <= 1_000_000:
                raise ValueError()
            samples.append({'at_ms': item['at_ms'], 'data': image})
        if any(a['at_ms'] > b['at_ms'] for a, b in zip(samples, samples[1:])):
            raise ValueError()
        return samples
    except (subprocess.SubprocessError, OSError, ValueError, TypeError, KeyError):
        raise ValueError('视频抽帧失败或超过处理时限') from None


def _decode(data, mime, count):
    import av
    from app.production.video_probe import inspect
    inspect(data, mime)
    fmt = 'mov' if mime == 'video/mp4' else 'matroska'
    def deny(*args): raise ValueError('External I/O disabled')
    def opened():
        return av.open(io.BytesIO(data), format=fmt, io_open=deny,
                       options={'protocol_whitelist': '', 'err_detect': 'explode'})
    with opened() as container:
        n = sum(1 for _ in container.decode(video=0))
    if not n or n > 100000: raise ValueError()
    indices = {round(i * (n-1) / (min(count,n)-1)) for i in range(min(count,n))} if min(count,n)>1 else {0}
    samples = []
    with opened() as container:
        origin = float(container.start_time or 0) / av.time_base
        for index, frame in enumerate(container.decode(video=0)):
            if index in indices:
                picture = frame.to_image(); picture.thumbnail((640,640))
                out = io.BytesIO(); picture.convert('RGB').save(out, format='JPEG', quality=80)
                samples.append({'at_ms': max(0,round((frame.time-origin)*1000)),
                                'jpeg': base64.b64encode(out.getvalue()).decode('ascii')})
    return samples


if __name__ == '__main__':
    try:
        count = int(sys.argv[2]); data = sys.stdin.buffer.read(MAX_VIDEO_BYTES+1)
        if not 1 <= count <= 12 or len(data)>MAX_VIDEO_BYTES: raise ValueError()
        print(json.dumps(_decode(data,sys.argv[1],count)))
    except Exception:
        raise SystemExit(1) from None
