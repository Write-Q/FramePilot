"""业务数据约定：模型输出与接口输入都必须通过这些检查。"""
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field, model_validator


# 业务模型的公共基类：拒绝多余字段并裁剪字符串首尾空白；未开启 strict=True。
class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


# 新建项目的请求体：第一次提交故事使用它。
class CreateProject(StrictModel):
    # 用户首次输入，可以是标题、片段或完整故事。
    story: str = Field(min_length=1, max_length=16000)
    # 创作模式：direct 原稿交接；faithful 兼容旧模式；collaborative 协作；free 自由编剧。
    mode: Literal['direct', 'faithful', 'collaborative', 'free'] = 'collaborative'
    # 用户明确要求，例如时长、风格和不可更改的设定。
    constraints: str = Field(default='', max_length=3000)


# 对一条审核问题的处理选择，不等于确认时接受问题现状。
class IssueDecision(StrictModel):
    # 当前审核问题的编号，用来定位用户正在处理哪条建议。
    issue_id: str = Field(min_length=1)
    # adopt 采用原建议；replace 使用用户方案；keep 保留设定并解释。
    choice: Literal['adopt', 'replace', 'keep']
    # 替代方案或保留理由；采用原建议时可为空。
    text: str = Field(default='', max_length=1500)

    @model_validator(mode='after')
    def check_text(self):
        if self.choice in ('replace', 'keep') and not self.text:
            raise ValueError('替代方案或保留原设定需要填写说明')
        return self


# 人工暂停后的请求体：选择方向、修订、仅澄清或确认。
class ResumeProject(StrictModel):
    # 正文版本号，不等于修订次数；用于历史保存及拒绝过期操作。
    version: int = Field(ge=1)
    # 本次人工暂停的编号；需与服务端当前暂停一致才能恢复。
    interrupt_id: str = Field(min_length=1)
    # revise 改稿；confirm 确认；clarify 只复审；choose 选故事方向。
    action: Literal['revise', 'confirm', 'clarify', 'choose']
    # 逐条处理意见；每个元素都按 IssueDecision 校验。
    decisions: list[IssueDecision] = Field(default_factory=list, max_length=20)
    # 所选候选方向的服务端编号。
    direction_id: str = Field(default='', max_length=50)
    # 本次整体补充信息或修改要求。
    feedback: str = Field(default='', max_length=3000)
    # 确认时接受现状的问题编号；不表示执行 AI 修改建议。
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


# 一个概括维度；text 是总结，evidence 是引用，两者用途不同。
class Facet(StrictModel):
    # 该维度的概括总结，供用户阅读，不必逐字照抄原文。
    text: str = Field(max_length=2000)
    # 来源标签；Facet 标记概括来源，Evidence 标记引用来自哪份材料。
    source: Literal['original', 'user', 'ai_suggestion', 'unknown']
    # 原文证据；Facet 中是字符串，ReviewIssue 中是 Evidence 列表。
    evidence: str = Field(default='', max_length=2000)


# 十维概括卡片。字段目前都是单个 Facet，尚不是独立实体列表。
class StoryCard(StrictModel):
    # 主题维度的概括、来源和证据。
    theme: Facet
    # 人物维度的概括、来源和证据。
    characters: Facet
    # 情节维度的概括、来源和证据。
    plot: Facet
    # 道具维度的概括、来源和证据。
    props: Facet
    # 场景维度的概括、来源和证据。
    scenes: Facet
    # 动作维度的概括、来源和证据。
    actions: Facet
    # 镜头维度的概括、来源和证据。
    camera: Facet
    # 视觉风格维度的概括、来源和证据。
    visual_style: Facet
    # 声音维度的概括、来源和证据。
    sound: Facet
    # 节奏维度的概括、来源和证据。
    pacing: Facet


# 自由编剧构思阶段的输出，只包含故事骨架。
class StoryPlan(StrictModel):
    # 故事骨架，尚不是完整的可拍摄正文。
    outline: str = Field(min_length=1, max_length=6000)


# 协作模式的一个候选方向；方向编号由流程代码生成，不由模型提供。
class Direction(StrictModel):
    # 候选方向的简短名称。
    title: str = Field(min_length=1, max_length=100)
    # 故事骨架，尚不是完整的可拍摄正文。
    outline: str = Field(min_length=1, max_length=2000)


# 头脑风暴输出：必须给出 2～3 个候选方向。
class Brainstorm(StrictModel):
    # 候选创作方向；等待用户选择后才进入协作写稿。
    directions: list[Direction] = Field(min_length=2, max_length=3)


# 提取阶段输出：概括卡片与输入完整度判断。
class Extraction(StrictModel):
    # 当前正文对应的十维概括卡片。
    card: StoryCard
    # idea 想法/标题；fragment 片段；complete 完整故事，决定协作分支。
    input_kind: Literal['idea', 'fragment', 'complete'] = 'complete' 


# 继承 Extraction 的 card/input_kind，增加正文；首次写稿也复用此结构。
class Revision(Extraction):
    # 当前工作的剧本正文；修改它不会覆盖 original_story。
    draft: str = Field(min_length=1, max_length=20000)


# 一条审核证据；引用是否真实存在还需 workflow.py 校验。
class Evidence(StrictModel):
    # 来源标签；Facet 标记概括来源，Evidence 标记引用来自哪份材料。
    source: Literal['original', 'draft', 'constraints', 'feedback']
    # 逐字引用；结构校验通过后还要检查它是否出现在对应材料中。
    quote: str = Field(min_length=1, max_length=1000)


# 模型报告的一条审核问题；id、version 由程序在审核后补充。
class ReviewIssue(StrictModel):
    # continuity 连续性；constraint 约束冲突；missing 缺失；creative 创作建议。
    category: Literal['continuity', 'constraint', 'missing', 'creative']
    # 问题的具体说明。
    description: str = Field(min_length=1, max_length=1000)
    # 原文证据；Facet 中是字符串，ReviewIssue 中是 Evidence 列表。
    evidence: list[Evidence] = Field(min_length=1, max_length=4)
    # AI 针对此问题提出的修改建议，尚未代表用户授权执行。
    suggestion: str = Field(min_length=1, max_length=1000)
    # 关联的卡片字段名，供前端切换定位，可关联多个维度。
    related_facets: list[Literal['theme', 'characters', 'plot', 'props', 'scenes', 'actions', 'camera', 'visual_style', 'sound', 'pacing']] = Field(default_factory=list, max_length=10)
    # 模型判断是否需用户决策；路由还会结合模式及程序规则。
    needs_user: bool


# 一次审核的输出；空 issues 表示本次未报告问题，不保证剧情绝对正确。
class Review(StrictModel):
    # 当前待处理问题；空列表只表示本次未报告问题。
    issues: list[ReviewIssue] = Field(max_length=20)


# LangGraph 共享状态。TypedDict 仅描述类型，不提供 Pydantic 运行时校验；total=False 允许字段暂缺。
class StoryState(TypedDict, total=False):
    # idea 想法/标题；fragment 片段；complete 完整故事，决定协作分支。
    input_kind: str
    # 候选创作方向；等待用户选择后才进入协作写稿。
    directions: list[dict]
    # 服务端根据采用/替换/保留选择整理的本轮授权指令。
    revision_instructions: list[dict]
    # 历次用户选择及授权记录，供追溯和导出。
    decision_history: list[dict]
    # 逐条处理时未被选择的旧问题，避免复审漏报后被当成已解决。
    protected_issues: list[dict]
    # 本轮是否仅澄清；为真时复审后不自动改稿。
    clarification_only: bool
    # 故事骨架，尚不是完整的可拍摄正文。
    outline: str
    # 连续审核仍保留全部旧问题编号的次数，不是语义质量分数。
    stagnant_rounds: int
    # 项目唯一编号，同时用作 LangGraph thread_id。
    project_id: str
    # 用户最初输入，保留原样供追溯；不随改稿覆盖。
    original_story: str
    # 当前工作的剧本正文；修改它不会覆盖 original_story。
    draft: str
    # 创作模式：direct 原稿交接；faithful 兼容旧模式；collaborative 协作；free 自由编剧。
    mode: str
    # 用户明确要求，例如时长、风格和不可更改的设定。
    constraints: str
    # 当前正文对应的十维概括卡片。
    card: dict
    # 当前待处理问题；空列表只表示本次未报告问题。
    issues: list[dict]
    # 历次审核的版本和问题列表。
    review_history: list[dict]
    # 累计用户反馈及选定方向，作为后续模型调用材料。
    feedback_history: list[str]
    # 正文版本号，不等于修订次数；用于历史保存及拒绝过期操作。
    version: int
    # 最近完成有效审核的正文版本，确认时必须等于当前 version。
    reviewed_version: int
    # 累计正文修订次数，上限 3；首次写稿和仅澄清不算修订。
    revision_count: int
    # 业务状态，例如 running、awaiting_input、confirmed、failed。
    status: str
    # 图的路由目标（如 human/revise/review/end），与业务状态不同。
    next_step: str
    # 暂停或结束原因，面向用户展示。
    stop_reason: str
    # 确认时接受现状的问题编号；不表示执行 AI 修改建议。
    accepted_issue_ids: list[str]
    # 执行失败说明；空字符串表示没有记录错误。
    error: str
