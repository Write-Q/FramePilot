"""Real local media fixtures; no AI model quality claims."""
import io
import math
import struct
import subprocess
import wave

import av
import pytest
from PIL import ImageChops, ImageStat

from app.production.editing_render import EditingRenderError, render_timeline


def video(path, width=96, height=54, shade=80, seconds=0.5):
    with av.open(str(path), 'w') as output:
        stream = output.add_stream('libx264', rate=24)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        for index in range(round(seconds * 24)):
            frame = av.VideoFrame(width, height, 'yuv420p')
            for idx, plane in enumerate(frame.planes):
                plane.update(bytes([shade if idx == 0 else 128]) * plane.buffer_size)
            frame.pts = index
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return {'path': path, 'start_ms': 0, 'end_ms': round(seconds * 1000), 'gain': 1}


def wav(path, seconds=0.2):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', round(10000 * math.sin(i * 2 * math.pi * 440 / 48000))) for i in range(round(seconds * 48000))))
    return {'path': path, 'offset_ms': 100, 'gain': 0.5, 'loop': True}


def decode(data):
    with av.open(io.BytesIO(data)) as source:
        size = (source.streams.video[0].width, source.streams.video[0].height)
        frames = list(source.decode(video=0))
    with av.open(io.BytesIO(data)) as source:
        audio_frames = list(source.decode(audio=0))
    return size, frames, audio_frames


def samples(frames):
    return [value[0] for frame in frames for plane in frame.planes for value in struct.iter_unpack('<f', bytes(plane)[:frame.samples * 4])]


def test_two_clips_are_normalized_concatenated_and_silent(tmp_path):
    clips = [video(tmp_path / 'one.mp4'), video(tmp_path / 'two.mp4', 54, 96, 180)]
    size, frames, sound = decode(render_timeline({'preset': 'landscape'}, clips, []))
    assert size == (1280, 720)
    assert len(frames) == 24
    assert frames[0].to_image().getpixel((640, 360))[0] < frames[-1].to_image().getpixel((640, 360))[0]
    assert sound and not any(samples(sound))


def test_wav_offset_loop_and_gain_make_audible_mix(tmp_path):
    clips = [video(tmp_path / 'one.mp4')]
    size, frames, sound = decode(render_timeline({'preset': 'square'}, clips, [wav(tmp_path / 'music.wav')]))
    assert size == (720, 720)
    assert len(frames) == 12
    assert max(abs(x) for x in samples(sound)) > 0.05
    assert sound[0].sample_rate == 48000
    assert sound[0].layout.name == 'stereo'


def test_chinese_subtitles_change_pixels_only_in_active_interval(tmp_path):
    clips = [video(tmp_path / 'one.mp4', seconds=1)]
    _, clean, _ = decode(render_timeline({'preset': 'square'}, clips, []))
    _, titled, _ = decode(render_timeline({'preset': 'square', 'subtitles': [
        {'start_ms': 500, 'end_ms': 1000, 'text': '中文 字幕 {\\pos(0,0)}\n第二行'}]}, clips, []))
    assert ImageStat.Stat(ImageChops.difference(clean[2].to_image(), titled[2].to_image())).mean[0] < 0.1
    assert ImageStat.Stat(ImageChops.difference(clean[18].to_image(), titled[18].to_image())).mean[0] > 0.2


@pytest.mark.parametrize('change', [
    {'start_ms': -1}, {'end_ms': 100}, {'end_ms': 1000}, {'gain': 3}, {'gain': float('nan')}, {'start_ms': True},
])
def test_invalid_clip_rejected(tmp_path, change):
    clip = video(tmp_path / 'one.mp4') | change
    with pytest.raises(EditingRenderError):
        render_timeline({}, [clip], [])


@pytest.mark.parametrize('timeline', [
    {'preset': 'command'}, {'subtitles': [{'start_ms': 0, 'end_ms': 501, 'text': 'x'}]},
    {'subtitles': [{'start_ms': 0, 'end_ms': 500, 'text': 'x' * 201}]},
])
def test_invalid_timeline_rejected(tmp_path, timeline):
    with pytest.raises(EditingRenderError):
        render_timeline(timeline, [video(tmp_path / 'one.mp4')], [])


def test_corrupt_input_rejected(tmp_path):
    path = tmp_path / 'bad.mp4'
    path.write_bytes(b'bad')
    with pytest.raises(EditingRenderError):
        render_timeline({}, [{'path': path, 'start_ms': 0, 'end_ms': 500, 'gain': 1}], [])


def test_timeout_is_sanitized(tmp_path, monkeypatch):
    clip = video(tmp_path / 'one.mp4')
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('private/path', 1)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(EditingRenderError, match='timed out') as error:
        render_timeline({}, [clip], [])
    assert 'private' not in str(error.value)


def test_original_sound_gain_and_added_track_delay_are_preserved(tmp_path):
    from imageio_ffmpeg import get_ffmpeg_exe
    clip = video(tmp_path / 'silent.mp4', seconds=1)
    wav(tmp_path / 'source.wav', seconds=1)
    source = tmp_path / 'sound.mp4'
    subprocess.run([get_ffmpeg_exe(), '-v', 'error', '-nostdin', '-i', str(clip['path']), '-i', str(tmp_path / 'source.wav'), '-c:v', 'copy', '-c:a', 'aac', str(source)], check=True, timeout=15)
    clip['path'] = source
    _, _, sound = decode(render_timeline({'preset': 'portrait'}, [clip], []))
    _, _, quiet = decode(render_timeline({'preset': 'portrait'}, [clip | {'gain': 0}], []))
    assert max(abs(x) for x in samples(sound)) > 0.1
    assert not any(samples(quiet))
    _, _, mixed = decode(render_timeline({'preset': 'square'}, [video(tmp_path / 'silent2.mp4', seconds=1)], [wav(tmp_path / 'voice.wav') | {'offset_ms': 400, 'loop': False}]))
    assert not any(samples([f for f in mixed if float(f.time) < 0.3]))
    assert max(abs(x) for x in samples([f for f in mixed if 0.45 < float(f.time) < 0.55])) > 0.05
    assert max(abs(x) for x in samples([f for f in mixed if float(f.time) > 0.8])) < 0.001


@pytest.mark.parametrize('change', [
    {'offset_ms': -1}, {'offset_ms': 500}, {'loop': 'yes'}, {'gain': float('inf')},
])
def test_bad_audio_configuration_rejected(tmp_path, change):
    with pytest.raises(EditingRenderError):
        render_timeline({}, [video(tmp_path / 'clip.mp4')], [wav(tmp_path / 'audio.wav') | change])


def test_missing_libass_is_explicit(tmp_path, monkeypatch):
    import app.production.editing_render as module
    original = module._run
    def no_ass(args, timeout, **kwargs):
        result = original(args, timeout, **kwargs)
        return '\n'.join(line for line in result.splitlines() if ' ass ' not in line)
    monkeypatch.setattr(module, '_run', no_ass)
    with pytest.raises(EditingRenderError, match='libass'):
        render_timeline({'subtitles': [{'start_ms': 0, 'end_ms': 500, 'text': '中文'}]}, [video(tmp_path / 'clip.mp4')], [])


def test_ffmpeg_failure_is_sanitized(tmp_path, monkeypatch):
    import app.production.editing_render as module
    original = subprocess.run
    def fail_render(args, **kwargs):
        if '-filter_complex' in args:
            return subprocess.CompletedProcess(args, 1, b'', b'private/source/path')
        return original(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', fail_render)
    with pytest.raises(EditingRenderError) as error:
        render_timeline({}, [video(tmp_path / 'clip.mp4')], [])
    assert 'private' not in str(error.value)


def test_ass_override_injection_is_rendered_as_literal_text():
    from app.production.editing_render import _ass
    text = _ass([{'start_ms': 0, 'end_ms': 500, 'text': '{\\p1}m 0 0 l 20 20\n中文'}], 720, 720)
    assert '{\\p1}' not in text
    assert '｛＼p1｝' in text
    assert r'\N中文' in text


def test_invalid_preset_type_is_an_editing_error(tmp_path):
    with pytest.raises(EditingRenderError):
        render_timeline({'preset': []}, [video(tmp_path / 'clip.mp4')], [])


def test_webm_source_is_rendered_to_h264_mp4(tmp_path):
    from imageio_ffmpeg import get_ffmpeg_exe
    clip = video(tmp_path / 'original.mp4')
    webm = tmp_path / 'source.webm'
    subprocess.run([get_ffmpeg_exe(), '-v', 'error', '-nostdin', '-i', str(clip['path']), '-c:v', 'libvpx-vp9', str(webm)], check=True, timeout=15)
    result = render_timeline({'preset': 'square'}, [clip | {'path': webm}], [])
    with av.open(io.BytesIO(result)) as media:
        assert media.streams.video[0].codec_context.name == 'h264'
        assert len(list(media.decode(video=0))) == 12


def test_missing_source_path_is_a_render_error():
    with pytest.raises(EditingRenderError):
        render_timeline({}, [{'start_ms': 0, 'end_ms': 500}], [])


def test_integer_overflow_input_is_a_render_error():
    with pytest.raises(EditingRenderError):
        render_timeline({}, [{'start_ms': 10**1000, 'end_ms': 500}], [])


def test_total_clip_limit_and_collection_limits():
    clip = {'start_ms': 0, 'end_ms': 600000}
    with pytest.raises(EditingRenderError, match='600 seconds'):
        render_timeline({}, [clip, clip], [])
    with pytest.raises(EditingRenderError):
        render_timeline({}, [clip] * 31, [])
    with pytest.raises(EditingRenderError):
        render_timeline({'subtitles': [{}] * 101}, [clip], [])
    with pytest.raises(EditingRenderError):
        render_timeline({}, [clip], [{}] * 5)


def test_mixing_multiple_loud_tracks_limits_peak(tmp_path):
    clip = video(tmp_path / 'clip.mp4')
    track = wav(tmp_path / 'loud.wav') | {'gain': 2, 'offset_ms': 0}
    _, _, sound = decode(render_timeline({'preset': 'square'}, [clip], [track] * 4))
    assert 0.5 < max(abs(x) for x in samples(sound)) <= 1
