"""Video evidence and manual findings; no inferred semantic approval."""
from typing import Literal

from pydantic import Field, model_validator
from app.production.contracts import Contract


class CreateInspection(Contract):
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    count: int = Field(default=8, ge=1, le=12, strict=True)


class ManualFinding(Contract):
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    severity: Literal['low', 'medium', 'high']
    description: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def ordered_interval(self):
        if self.end_ms < self.start_ms:
            raise ValueError('问题结束时间不能早于开始时间')
        return self


class ManualReview(Contract):
    expected_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    decision: Literal['reviewed', 'needs_revision']
    findings: list[ManualFinding] = Field(default_factory=list, max_length=20)
    comment: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def revision_reason(self):
        if self.decision == 'needs_revision' and not self.findings:
            raise ValueError('需要修改时请至少记录一项带时间范围的具体问题')
        return self
