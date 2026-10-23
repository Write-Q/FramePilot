"""Bounded, local-only FFmpeg timeline rendering.

The service resolves/checksums source files; this module snapshots only validated
MP4/WebM/WAV bytes into its private work directory. No user text enters a filter graph.
"""
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import av
import imageio_ffmpeg

MAX_OUTPUT_BYTES = 256 * 1024 * 1024
PRESETS = {'landscape': (1280, 720), 'portrait': (720, 1280), 'square': (720, 720)}


class EditingRenderError(ValueError):
    """Actionable render failure safe to expose without private paths."""


def render_timeline(timeline: dict, clips: list[dict], audio: list[dict], *, timeout=120) -> bytes:
    """Return H.264/AAC MP4 bytes or an actionable, path-free ValueError.

    Paths must be trusted storage paths supplied by the service, never HTTP user
    paths. Inputs are copied before FFmpeg runs to avoid metadata/content races.
    """
    total = _validate(timeline, clips, audio, timeout)
    try:
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except (RuntimeError, OSError):
        raise EditingRenderError('FFmpeg is unavailable; install the configured local renderer.') from None
    subtitles = timeline.get('subtitles', [])
    _capabilities(executable, bool(subtitles), timeout)
    try:
        with tempfile.TemporaryDirectory(prefix='framepilot-render-') as directory:
            work = Path(directory)
            # Match PyAV's original stream timestamp coordinates. FFmpeg's
            # default input start-time subtraction would otherwise apply the
            # nonzero-origin compensation twice for ordinary single-track files.
            args = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-copyts', '-filter_complex_threads', '1']
            has_audio, origins = [], []
            for index, clip in enumerate(clips):
                name = f'clip{index}.mp4'
                metadata = _snapshot(clip.get('path'), work / name, 'video')
                if clip['end_ms'] > metadata['duration_ms'] + 1:
                    raise EditingRenderError('Clip trim exceeds the actual source duration.')
                has_audio.append(metadata['audio'])
                origins.append(metadata['origin_seconds'])
                args += ['-protocol_whitelist', 'file,pipe', '-f', metadata['format'], '-i', name]
            for index, track in enumerate(audio):
                name = f'audio{index}.wav'
                _snapshot(track.get('path'), work / name, 'audio')
                if track.get('loop', False):
                    args += ['-stream_loop', '-1']
                args += ['-protocol_whitelist', 'file,pipe', '-f', 'wav', '-i', name]
            width, height = PRESETS[timeline.get('preset', 'landscape')]
            filters, pairs = [], []
            for index, clip in enumerate(clips):
                # Timeline coordinates are relative to the first visible frame,
                # which need not have container PTS zero (e.g. audio preroll).
                start, end = origins[index] + clip['start_ms'] / 1000, origins[index] + clip['end_ms'] / 1000
                duration, gain = (clip['end_ms'] - clip['start_ms']) / 1000, float(clip.get('gain', 1))
                # Normalize timestamps before scale: FFmpeg 7 scale can discard
                # the EOF frame duration, causing fps after scale to lose a frame.
                filters.append(f'[{index}:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS,fps=24,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{index}]')
                if has_audio[index]:
                    # Keep the original soundtrack's offset from picture. An
                    # independent STARTPTS reset would pull delayed audio early.
                    filters.append(f'[{index}:a:0]atrim=start={start}:end={end},asetpts=PTS-{start}/TB,aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={gain},apad,atrim=duration={duration}[a{index}]')
                else:
                    filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration}[a{index}]')
                pairs.append(f'[v{index}][a{index}]')
            filters.append(''.join(pairs) + f'concat=n={len(clips)}:v=1:a=1[basevideo][baseaudio]')
            audio_labels = ['[baseaudio]']
            for index, track in enumerate(audio):
                input_index, offset = len(clips) + index, track.get('offset_ms', 0)
                gain = float(track.get('gain', 1))
                filters.append(f'[{input_index}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,atrim=duration={(total-offset)/1000},volume={gain},adelay={offset}:all=1[track{index}]')
                audio_labels.append(f'[track{index}]')
            filters.append(''.join(audio_labels) + f'amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95:level=0:latency=1[outaudio]')
            video_label = '[basevideo]'
            if subtitles:
                font = _subtitle_font()
                (work / 'fonts').mkdir()
                shutil.copyfile(font, work / 'fonts' / font.name)
                (work / 'captions.ass').write_text(_ass(subtitles, width, height), encoding='utf-8-sig')
                filters.append('[basevideo]ass=filename=captions.ass:fontsdir=fonts[outvideo]')
                video_label = '[outvideo]'
            args += ['-filter_complex', ';'.join(filters), '-map', video_label, '-map', '[outaudio]', '-t', str(total / 1000), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', '-fs', str(MAX_OUTPUT_BYTES + 1), 'result.mp4']
            _run(args, timeout, cwd=work)
            output = work / 'result.mp4'
            if not output.is_file() or not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
                raise EditingRenderError('Rendered MP4 is empty or exceeds the 256 MiB limit.')
            return output.read_bytes()
    except EditingRenderError:
        raise
    except (OSError, av.error.FFmpegError, ValueError, OverflowError):
        raise EditingRenderError('Local media could not be rendered; verify the source files and available disk space.') from None


def _number(value, label, low, high, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value) or (integer and not isinstance(value, int)):
        raise EditingRenderError(f'Invalid {label}.')
    return value


def _validate(timeline, clips, audio, timeout):
    if not isinstance(timeline, dict) or not isinstance(timeline.get('preset', 'landscape'), str) or timeline.get('preset', 'landscape') not in PRESETS:
        raise EditingRenderError('Unknown output preset.')
    _number(timeout, 'render timeout', 0.01, 3600)
    if not isinstance(clips, list) or not 1 <= len(clips) <= 30:
        raise EditingRenderError('A timeline requires 1 to 30 clips.')
    total = 0
    for clip in clips:
        if not isinstance(clip, dict):
            raise EditingRenderError('Invalid clip.')
        start = _number(clip.get('start_ms'), 'clip start', 0, 600000, integer=True)
        end = _number(clip.get('end_ms'), 'clip end', start + 200, 600000, integer=True)
        _number(clip.get('gain', 1), 'clip gain', 0, 2)
        total += end - start
    if total > 600000:
        raise EditingRenderError('Timeline exceeds 600 seconds.')
    subtitles = timeline.get('subtitles', [])
    if not isinstance(subtitles, list) or len(subtitles) > 100:
        raise EditingRenderError('At most 100 subtitles are allowed.')
    for subtitle in subtitles:
        if not isinstance(subtitle, dict):
            raise EditingRenderError('Invalid subtitle.')
        start = _number(subtitle.get('start_ms'), 'subtitle start', 0, total - 1, integer=True)
        _number(subtitle.get('end_ms'), 'subtitle end', start + 1, total, integer=True)
        text = subtitle.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(c) < 32 and c not in '\n\r\t' for c in text):
            raise EditingRenderError('Subtitle text requires 1 to 200 printable characters.')
    if not isinstance(audio, list) or len(audio) > 4:
        raise EditingRenderError('At most four added audio tracks are allowed.')
    for track in audio:
        if not isinstance(track, dict) or not isinstance(track.get('loop', False), bool):
            raise EditingRenderError('Invalid audio track.')
        _number(track.get('offset_ms', 0), 'audio offset', 0, total - 1, integer=True)
        _number(track.get('gain', 1), 'audio gain', 0, 2)
    return total


def _run(args, timeout, *, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise EditingRenderError('Local FFmpeg render timed out.') from None
    except OSError:
        raise EditingRenderError('FFmpeg could not start; check the local renderer installation.') from None
    if result.returncode:
        raise EditingRenderError('FFmpeg could not render the media; check source files and renderer capabilities.')
    return result.stdout.decode('utf-8', errors='replace')


def _capabilities(executable, subtitles, timeout):
    filters = _run([executable, '-hide_banner', '-filters'], timeout)
    encoders = _run([executable, '-hide_banner', '-encoders'], timeout)
    required = ['concat', 'amix', 'alimiter', 'scale', 'pad', 'fps', 'atrim', 'anullsrc', 'adelay'] + (['ass'] if subtitles else [])
    for name in required:
        if not re.search(r'^\s*\S+\s+' + re.escape(name) + r'\s', filters, re.MULTILINE):
            label = 'libass subtitles (ass)' if name == 'ass' else name
            raise EditingRenderError(f'FFmpeg lacks the required {label} filter.')
    for name in ['libx264', 'aac']:
        if not re.search(r'^\s*\S+\s+' + name + r'\s', encoders, re.MULTILINE):
            raise EditingRenderError(f'FFmpeg lacks the required {name} encoder.')


def _snapshot(path, target, kind):
    if not isinstance(path, Path) or not path.is_file():
        raise EditingRenderError('A local source media file is missing.')
    limit = MAX_OUTPUT_BYTES if kind == 'video' else 20 * 1024 * 1024
    with path.open('rb') as source:
        data = source.read(limit + 1)
    if not data or len(data) > limit:
        raise EditingRenderError('Source media exceeds its size limit.')
    def reject_external(*args):
        raise ValueError('External media resources are disabled')
    origin = 0.0
    try:
        if kind == 'video':
            media_format = 'mov' if data[4:8] == b'ftyp' else 'matroska' if data[:4] == b'\x1aE\xdf\xa3' else None
            if media_format is None:
                raise ValueError()
        else:
            media_format = 'wav'
        with av.open(io.BytesIO(data), format=media_format, io_open=reject_external, options={'protocol_whitelist': ''}) as media:
            videos, sounds = list(media.streams.video), list(media.streams.audio)
            if kind == 'video':
                codecs = {'h264'} if media_format == 'mov' else {'vp8', 'vp9'}
                if len(videos) != 1 or len(sounds) > 1 or videos[0].codec_context.name not in codecs:
                    raise ValueError()
                stream = videos[0]
                if not 0 < stream.codec_context.width * stream.codec_context.height <= 25_000_000:
                    raise ValueError()
                duration = float(stream.duration * stream.time_base) if stream.duration is not None else float(media.duration or 0) / av.time_base
                first = next(media.decode(video=0), None)
                if first is None or first.time is None:
                    raise ValueError()
                origin = float(first.time)
                if not math.isfinite(origin):
                    raise ValueError()
            else:
                if videos or len(sounds) != 1 or not sounds[0].codec_context.name.startswith('pcm_'):
                    raise ValueError()
                stream = sounds[0]
                duration = float(stream.duration * stream.time_base) if stream.duration is not None else 0
            if not math.isfinite(duration) or not 0 < duration <= 600.1:
                raise ValueError()
    except (ValueError, av.error.FFmpegError, OverflowError):
        raise EditingRenderError('Source media is invalid; use H.264 MP4 or VP8/VP9 WebM clips and PCM WAV audio.') from None
    target.write_bytes(data)
    return {'duration_ms': round(duration * 1000), 'audio': bool(sounds), 'format': media_format,
            'origin_seconds': origin}


def _subtitle_font():
    candidates = [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc', Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for font in candidates:
        if font.is_file():
            return font
    raise EditingRenderError('Chinese subtitle font is unavailable; install Microsoft YaHei or Noto Sans CJK.')


def _ass(subtitles, width, height):
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,40,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def stamp(ms):
        cs = ms // 10
        return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'
    lines = []
    for subtitle in subtitles:
        # Full-width literal forms cannot become ASS override tags or escapes.
        text = subtitle['text'].replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\r\n', '\n').replace('\r', '\n').replace('\n', r'\N').replace('\t', '    ')
        lines.append(f"Dialogue: 0,{stamp(subtitle['start_ms'])},{stamp(subtitle['end_ms'])},Default,,0,0,0,,{text}\n")
    return header + ''.join(lines)
