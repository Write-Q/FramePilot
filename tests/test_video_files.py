import io
import subprocess

import av
import pytest

from app.production.video_files import VideoFiles


def make_video(frames=10):
    """Actual H.264 MP4 fixture; not evidence of generated-video semantic quality."""
    output = io.BytesIO()
    with av.open(output, 'w', format='mp4') as container:
        stream = container.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 36, 'yuv420p'
        for index in range(frames):
            frame = av.VideoFrame(64, 36, 'yuv420p')
            for plane in frame.planes:
                plane.update(bytes([100 if plane == frame.planes[0] else 128]) * plane.buffer_size)
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return output.getvalue()


def test_real_mp4_fully_decoded_and_stored(tmp_path):
    data = make_video()
    files = VideoFiles(tmp_path)
    saved = files.put(data, 'video/mp4')
    assert saved['metadata'] == {'width': 64, 'height': 36, 'duration_ms': 1000}
    assert files.verify(saved).read_bytes() == data
    assert files.put(data, 'video/mp4')['storage_key'] != saved['storage_key']
    assert files.validated_video is True


@pytest.mark.parametrize('data,mime', [(b'fake', 'video/mp4'), (b'#EXTM3U\nhttp://localhost/video', 'video/mp4'),
    (b'fake', 'application/octet-stream'), (make_video(), 'video/webm'), (make_video()[:100], 'video/mp4')])
def test_bad_video_rejected_without_files(tmp_path, data, mime):
    with pytest.raises(ValueError):
        VideoFiles(tmp_path).put(data, mime)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('key', ['../x.mp4', 'C:\\secret.mp4', '/etc/file', 'a/b.mp4', '', 'not-uuid.mp4'])
def test_path_rejects_invalid_storage_keys(tmp_path, key):
    with pytest.raises(ValueError):
        VideoFiles(tmp_path).path(key)


def test_verify_detects_changed_content(tmp_path):
    files = VideoFiles(tmp_path)
    saved = files.put(make_video(2), 'video/mp4')
    path = files.path(saved['storage_key'])
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    with pytest.raises(ValueError):
        files.verify(saved)


def test_probe_timeout_is_sanitized_and_writes_nothing(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('private/path', 30)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(ValueError) as caught:
        VideoFiles(tmp_path).put(make_video(), 'video/mp4')
    assert 'private' not in str(caught.value)
    assert not list(tmp_path.iterdir())


def test_byte_limit_checked_before_subprocess(tmp_path, monkeypatch):
    import app.production.video_files as module
    monkeypatch.setattr(module, 'MAX_VIDEO_BYTES', 2)
    with pytest.raises(ValueError):
        VideoFiles(tmp_path).put(b'123', 'video/mp4')
