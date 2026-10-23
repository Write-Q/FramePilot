"""Child-process decoder. Reads bounded bytes, never opens media-supplied resources."""
import io
import json
import sys
import av

MAX_BYTES = 256 * 1024 * 1024


def inspect(data, mime):
    if mime == 'video/mp4' and data[4:8] == b'ftyp':
        fmt, codecs = 'mov', {'h264'}
    elif mime == 'video/webm' and data[:4] == b'\x1aE\xdf\xa3':
        fmt, codecs = 'matroska', {'vp8', 'vp9'}
    else:
        raise ValueError()

    def reject_external(*args):
        raise ValueError('External media resources are disabled')

    with av.open(io.BytesIO(data), format=fmt, io_open=reject_external,
                 options={'protocol_whitelist': '', 'err_detect': 'explode'}) as container:
        videos = list(container.streams.video)
        if len(videos) != 1 or len(container.streams.audio) > 1 or any(s.type not in ('video', 'audio') for s in container.streams):
            raise ValueError()
        stream = videos[0]
        width, height = stream.codec_context.width, stream.codec_context.height
        if stream.codec_context.name not in codecs or not 0 < width * height <= 25_000_000:
            raise ValueError()
        for s in container.streams:
            s.codec_context.thread_count = 1
        count, total, end, start = 0, 0, 0.0, None
        picture_start, picture_end = None, 0.0
        for packet in container.demux():
            for frame in packet.decode():
                total += 1
                if total > 100000 or frame.is_corrupt:
                    raise ValueError()
                if isinstance(frame, av.VideoFrame):
                    count += 1
                    if frame.width != width or frame.height != height or frame.time is None:
                        raise ValueError()
                    duration = float(frame.duration * frame.time_base) if frame.duration else 1 / float(stream.average_rate or 25)
                    picture_start = float(frame.time) if picture_start is None else min(picture_start, float(frame.time))
                    picture_end = max(picture_end, float(frame.time) + duration)
                else:
                    if frame.time is None or not frame.sample_rate:
                        raise ValueError()
                    duration = frame.samples / frame.sample_rate
                start = float(frame.time) if start is None else min(start, float(frame.time))
                end = max(end, float(frame.time) + duration)
                if end - start > 600:
                    raise ValueError()
        if not count or (stream.frames and count != stream.frames) or end <= 0:
            raise ValueError()
        # A timeline cuts picture. A longer source soundtrack must not make a
        # default trim extend beyond the last picture frame; audio is trimmed
        # to this visual duration by the renderer. All streams remain bounded.
        return {'width': width, 'height': height, 'duration_ms': round((picture_end - picture_start) * 1000)}


if __name__ == '__main__':
    try:
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            raise ValueError()
        print(json.dumps(inspect(data, sys.argv[1])))
    except Exception:
        raise SystemExit(1) from None
