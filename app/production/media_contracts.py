"""Explicit shot-media requests; provider-specific video protocols are not guessed."""
from typing import Literal
from pydantic import Field, field_validator
from app.production.contracts import Contract, ProfileRef


class CreateMediaRun(Contract):
    expected_version: int = Field(ge=1, strict=True)
    shot_key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    frame_role: Literal['first', 'key', 'last'] = 'first'
    kind: Literal['image'] = 'image'
    profile: ProfileRef
    prompt: str = Field(default='', max_length=12000)
    size: str = Field(default='1536x864', pattern=r'^[1-9][0-9]{1,3}x[1-9][0-9]{1,3}$')
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')

    @field_validator('size')
    @classmethod
    def check_size(cls, value):
        width, height = map(int, value.split('x'))
        if width * height > 25_000_000:
            raise ValueError('图片尺寸超过本地处理上限')
        return value


class SelectMedia(Contract):
    expected_version: int = Field(ge=1, strict=True)
