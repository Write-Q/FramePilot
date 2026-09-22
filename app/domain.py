"""业务数据约定：模型输出与接口输入都必须通过这些检查。"""
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CreateProject(StrictModel):
    story: str = Field(min_length=1, max_length=16000)
    mode: Literal['direct', 'faithful', 'collaborative', 'free'] = 'collaborative'
    constraints: str = Field(default='', max_length=3000)


class IssueDecision(StrictModel):
    issue_id: str = Field(min_length=1)
    choice: Literal['adopt', 'replace', 'keep']
    text: str = Field(default='', max_length=1500)

    @model_validator(mode='after')
    def check_text(self):
        if self.choice in ('replace', 'keep') and not self.text:
            raise ValueError('替代方案或保留原设定需要填写说明')
        return self


class ResumeProject(StrictModel):
    version: int = Field(ge=1)
    interrupt_id: str = Field(min_length=1)
    action: Literal['revise', 'confirm', 'clarify', 'choose']
    decisions: list[IssueDecision] = Field(default_factory=list, max_length=20)
    direction_id: str = Field(default='', max_length=50)
    feedback: str = Field(default='', max_length=3000)
    accepted_issue_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def check_feedback(self):
        if self.action in ('revise', 'clarify') and not self.feedback and not self.decisions:
            raise ValueError('修订需要明确填写补充内容或修改要求')
        if self.action == 'choose' and not self.direction_id:
            raise ValueError('请选择一个故事方向')
        if self.action in ('confirm', 'choose') and self.decisions:
            raise ValueError('此操作不能同时提交逐条修改意见')
        if self.action == 'clarify' and any(d.choice != 'keep' for d in self.decisions):
            raise ValueError('仅澄清不能同时采用或替换修改建议')
        if self.action == 'confirm' and self.feedback:
            raise ValueError('确认版本不能同时提交新反馈')
        return self


class Facet(StrictModel):
    text: str = Field(max_length=2000)
    source: Literal['original', 'user', 'ai_suggestion', 'unknown']
    evidence: str = Field(default='', max_length=2000)


class StoryCard(StrictModel):
    theme: Facet
    characters: Facet
    plot: Facet
    props: Facet
    scenes: Facet
    actions: Facet
    camera: Facet
    visual_style: Facet
    sound: Facet
    pacing: Facet


class StoryPlan(StrictModel):
    outline: str = Field(min_length=1, max_length=6000)


class Direction(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    outline: str = Field(min_length=1, max_length=2000)


class Brainstorm(StrictModel):
    directions: list[Direction] = Field(min_length=2, max_length=3)


class Extraction(StrictModel):
    card: StoryCard
    input_kind: Literal['idea', 'fragment', 'complete'] = 'complete' 


class Revision(Extraction):
    draft: str = Field(min_length=1, max_length=20000)


class Evidence(StrictModel):
    source: Literal['original', 'draft', 'constraints', 'feedback']
    quote: str = Field(min_length=1, max_length=1000)


class ReviewIssue(StrictModel):
    category: Literal['continuity', 'constraint', 'missing', 'creative']
    description: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)
    suggestion: str = Field(min_length=1, max_length=1000)
    related_facets: list[Literal['theme', 'characters', 'plot', 'props', 'scenes', 'actions', 'camera', 'visual_style', 'sound', 'pacing']] = Field(default_factory=list, max_length=10)
    needs_user: bool


class Review(StrictModel):
    issues: list[ReviewIssue] = Field(max_length=20)


class StoryState(TypedDict, total=False):
    input_kind: str
    directions: list[dict]
    revision_instructions: list[dict]
    decision_history: list[dict]
    protected_issues: list[dict]
    clarification_only: bool
    outline: str
    stagnant_rounds: int
    project_id: str
    original_story: str
    draft: str
    mode: str
    constraints: str
    card: dict
    issues: list[dict]
    review_history: list[dict]
    feedback_history: list[str]
    version: int
    reviewed_version: int
    revision_count: int
    status: str
    next_step: str
    stop_reason: str
    accepted_issue_ids: list[str]
    error: str
