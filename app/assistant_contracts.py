"""Bounded assistant input and model output; model proposals are data only."""
from typing import Literal
from pydantic import Field
from app.production.contracts import Contract, EffortChoice, ProfileRef

ActionKind = Literal['writer_create', 'writer_choose', 'writer_revise', 'writer_clarify',
    'storyboard_generate', 'storyboard_revise', 'storyboard_review', 'image_generate',
    'image_select', 'video_select', 'video_inspect', 'timeline_save', 'export_create']


class CreateThread(Contract):
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class Context(Contract):
    stage: Literal['writer', 'storyboard', 'editing']
    storyboard_id: str | None = Field(default=None, min_length=1, max_length=64)
    shot_key: str | None = Field(default=None, min_length=1, max_length=64)
    selection: str | None = Field(default=None, max_length=4000)
    workspace_dirty: bool = False


class Message(Contract):
    expected_revision: int = Field(ge=0, strict=True)
    text: str = Field(min_length=1, max_length=8000)
    context: Context
    profile: ProfileRef
    reasoning_effort: EffortChoice = 'default'
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')


class Decision(Contract):
    decision: Literal['accept', 'reject']
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    workspace_dirty: bool = False


class Proposal(Contract):
    kind: ActionKind
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default='', max_length=2000)
    params: dict


class Reply(Contract):
    reply: str = Field(min_length=1, max_length=12000)
    proposals: list[Proposal] = Field(default_factory=list, max_length=4)


# Descriptive aliases for clients that prefer request-qualified names.
CreateThreadRequest = CreateThread
AssistantMessageRequest = Message
ProposalDecision = Decision
