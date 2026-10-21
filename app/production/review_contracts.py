"""文字分镜审核契约；报告不是用户批准或实际视频审核。"""
from typing import Literal

from pydantic import Field, model_validator
from app.production.contracts import Contract, ProfileRef, EffortChoice


class ReviewRequest(Contract):
    expected_version: int = Field(ge=1, strict=True)
    profile: ProfileRef
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    reasoning_effort: EffortChoice = 'default'


class ReviewEvidence(Contract):
    source: Literal['script', 'scene', 'shot']
    key: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,64}$')
    field: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.]+$')
    quote: str = Field(min_length=1, max_length=2000)


class ReviewIssue(Contract):
    key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    severity: Literal['high', 'medium', 'low']
    category: Literal['fidelity', 'continuity', 'spatial', 'timing', 'dialogue', 'frame', 'missing_information']
    certainty: Literal['supported', 'needs_confirmation']
    shot_keys: list[str] = Field(default_factory=list, max_length=20)
    scene_keys: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(min_length=1, max_length=2000)
    suggestion: str = Field(min_length=1, max_length=2000)
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=8)

    @model_validator(mode='after')
    def check_location(self):
        if len(set(self.shot_keys)) != len(self.shot_keys) or len(set(self.scene_keys)) != len(self.scene_keys):
            raise ValueError('问题定位不能重复')
        if not self.shot_keys and not self.scene_keys and self.category not in ('fidelity', 'missing_information'):
            raise ValueError('此类问题需要定位到镜头或场次')
        return self


class ReviewReport(Contract):
    schema_version: Literal[1] = 1
    issues: list[ReviewIssue] = Field(max_length=50)

    @model_validator(mode='after')
    def check_keys(self):
        if len({issue.key for issue in self.issues}) != len(self.issues):
            raise ValueError('审核问题编号不能重复')
        return self
