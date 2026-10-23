"""Bounded timeline inputs. Clients identify owned assets, never filesystem paths."""
from typing import Literal
from pydantic import Field, model_validator
from app.production.contracts import Contract


class TimelineClip(Contract):
    run_id: str = Field(min_length=1, max_length=64)
    start_ms: int = Field(ge=0, le=1800000, strict=True)
    end_ms: int = Field(ge=200, le=1800000, strict=True)
    gain: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)

    @model_validator(mode='after')
    def interval(self):
        if self.end_ms - self.start_ms < 200:
            raise ValueError('片段至少200毫秒')
        return self


class Subtitle(Contract):
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=1, strict=True)
    text: str = Field(min_length=1, max_length=200)


class AudioTrack(Contract):
    asset_id: str = Field(min_length=1, max_length=64)
    offset_ms: int = Field(default=0, ge=0, strict=True)
    gain: float = Field(default=1, ge=0, le=2, allow_inf_nan=False)
    loop: bool = Field(default=False, strict=True)


class TimelineContent(Contract):
    preset: Literal['landscape', 'portrait', 'square'] = 'landscape'
    clips: list[TimelineClip] = Field(min_length=1, max_length=30)
    subtitles: list[Subtitle] = Field(default_factory=list, max_length=100)
    audio_tracks: list[AudioTrack] = Field(default_factory=list, max_length=4)

    @model_validator(mode='after')
    def intervals(self):
        total = sum(clip.end_ms - clip.start_ms for clip in self.clips)
        if total > 600000:
            raise ValueError('成片总长不超过600秒')
        if any(sub.end_ms <= sub.start_ms or sub.end_ms > total for sub in self.subtitles):
            raise ValueError('字幕区间必须在成片内')
        if any(track.offset_ms >= total for track in self.audio_tracks):
            raise ValueError('音轨起点必须在成片内')
        return self


class TimelineRequest(Contract):
    expected_version: int = Field(ge=0, strict=True)
    source_version: int = Field(ge=1, strict=True)
    content: TimelineContent


class ExportRequest(Contract):
    expected_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class AcceptRequest(Contract):
    comment: str = Field(default='', max_length=2000)
