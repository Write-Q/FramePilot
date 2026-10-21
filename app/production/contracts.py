"""制作数据契约。配置能力是用户声明，不是供应商能力验证结果。"""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Purpose = Literal['text', 'image', 'video', 'review', 'asr', 'tts']
Effort = Literal['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
EffortChoice = Literal['default', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']
REASONING_LEVELS = {'none': (), 'effort': ('low', 'medium', 'high'), 'deepseek': ('none', 'low', 'high', 'max')}


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, hide_input_in_errors=True)


class GenerationParameters(Contract):
    """受控公共参数；供应商扩展需在具体适配器中声明，禁止任意HTTP覆盖。"""
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=1, le=131072, strict=True)
    seed: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    reasoning_effort: Effort | None = None


class Capabilities(Contract):
    image_input: bool = False
    video_input: bool = False
    audio_input: bool = False
    first_frame: bool = False
    last_frame: bool = False
    max_reference_images: int = Field(default=0, ge=0, le=100, strict=True)
    max_duration_ms: int | None = Field(default=None, ge=1, le=3600000, strict=True)


class ModelConfig(Contract):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    purpose: Purpose
    adapter: str = Field(pattern=r'^[a-z][a-z0-9_]{0,63}$')
    base_url: str = Field(min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    api_key_env: str = Field(default='', pattern=r'^([A-Za-z_][A-Za-z0-9_]{0,127})?$')
    timeout_seconds: int = Field(default=90, ge=1, le=600, strict=True)
    parameters: GenerationParameters = Field(default_factory=GenerationParameters)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    reasoning_protocol: Literal['none', 'effort', 'deepseek'] = 'none'
    reasoning_levels: list[Effort] | None = Field(default=None, max_length=7)

    @model_validator(mode='after')
    def validate_reasoning(self):
        allowed = (() if self.reasoning_protocol == 'none' else
                   REASONING_LEVELS['deepseek'] if self.reasoning_protocol == 'deepseek' else
                   ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
        levels = self.reasoning_levels
        if levels is not None and (len(set(levels)) != len(levels) or any(x not in allowed for x in levels)):
            raise ValueError('思考档位须为接口支持的唯一值')
        available = levels if levels is not None else REASONING_LEVELS[self.reasoning_protocol]
        if self.parameters.reasoning_effort is not None and self.parameters.reasoning_effort not in available:
            raise ValueError('配置中的思考等级未声明支持')
        if self.reasoning_protocol != 'none' and (self.parameters.temperature is not None or self.parameters.seed is not None):
            raise ValueError('思考接口配置不接受自定义temperature/seed，避免参数被服务静默忽略')
        return self

    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value):
        try:
            url = urlsplit(value)
            port = url.port
            valid = (url.scheme in ('http', 'https') and url.hostname and not url.username
                     and not url.password and not url.query and not url.fragment
                     and not any(c.isspace() or ord(c) < 32 for c in value)
                     and '\\' not in value and (port is None or port > 0))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('API地址须为HTTP(S)，不能包含账号、密码、查询参数或片段')
        return value.rstrip('/')


class UpdateModelConfig(Contract):
    expected_version: int = Field(ge=1, strict=True)
    config: ModelConfig


class ProfileRef(Contract):
    profile_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1, strict=True)


class Scene(Contract):
    key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    title: str = Field(min_length=1, max_length=200)
    source_quote: str = Field(min_length=1, max_length=20000)


class ActionBeat(Contract):
    description: str = Field(min_length=1, max_length=1000)
    duration_ms: int | None = Field(default=None, ge=1, le=600000, strict=True)


class FramePrompts(Contract):
    """静态帧描述与video_prompt中的时间变化分开；空值不表示需要生成该帧。"""
    first: str = Field(default='', max_length=4000)
    key: str = Field(default='', max_length=4000)
    last: str = Field(default='', max_length=4000)


class DialogueLine(Contract):
    speaker: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2000)


class Shot(Contract):
    key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    scene_key: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    source_quote: str = Field(min_length=1, max_length=4000)
    purpose: str = Field(min_length=1, max_length=1000)
    action: str = Field(min_length=1, max_length=2000)
    duration_ms: int = Field(ge=1, le=600000, strict=True)
    shot_size: str = Field(default='', max_length=200)
    camera_angle: str = Field(default='', max_length=200)
    camera_motion: str = Field(default='', max_length=1000)
    composition: str = Field(default='', max_length=2000)
    screen_direction: str = Field(default='', max_length=1000)
    lighting: str = Field(default='', max_length=1000)
    continuity_notes: str = Field(default='', max_length=2000)
    action_beats: list[ActionBeat] = Field(default_factory=list, max_length=12)
    frame_prompts: FramePrompts = Field(default_factory=FramePrompts)
    dialogue: str = Field(default='', max_length=2000)
    sound: str = Field(default='', max_length=1000)
    state_start: str = Field(default='', max_length=1000)
    state_end: str = Field(default='', max_length=1000)
    image_prompt: str = Field(default='', max_length=4000)
    video_prompt: str = Field(default='', max_length=4000)
    characters: list[str] = Field(default_factory=list, max_length=30)
    dialogue_lines: list[DialogueLine] = Field(default_factory=list, max_length=30)
    creative_notes: str = Field(default='', max_length=2000)

    @field_validator('characters')
    @classmethod
    def check_characters(cls, value):
        if any(not name.strip() or len(name) > 200 for name in value) or len(set(value)) != len(value):
            raise ValueError('画面人物名称须非空、唯一且不超过200字')
        return value

    @model_validator(mode='after')
    def check_beat_duration(self):
        if sum(beat.duration_ms or 0 for beat in self.action_beats) > self.duration_ms:
            raise ValueError('动作节拍规划时长之和不能超过镜头时长；此为规划校验，不证明实际可拍')
        return self


class StoryboardContent(Contract):
    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    aspect_ratio: Literal['16:9', '9:16', '1:1'] = '16:9'
    visual_style: str = Field(default='', max_length=2000)
    scenes: list[Scene] = Field(min_length=1, max_length=50)
    shots: list[Shot] = Field(min_length=1, max_length=100)
    bindings: dict[Purpose, ProfileRef] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_keys(self):
        scenes = {s.key for s in self.scenes}
        if len(scenes) != len(self.scenes) or len({s.key for s in self.shots}) != len(self.shots):
            raise ValueError('场戏和镜头各自的稳定编号不能重复')
        if any(s.scene_key not in scenes for s in self.shots):
            raise ValueError('镜头引用的场戏不存在')
        return self


class CreateStoryboard(Contract):
    source_version: int = Field(ge=1, strict=True)
    content: StoryboardContent


class ReviseStoryboard(Contract):
    expected_version: int = Field(ge=1, strict=True)
    content: StoryboardContent


class ConfirmStoryboard(Contract):
    expected_version: int = Field(ge=1, strict=True)


class GenerateStoryboard(Contract):
    source_version: int = Field(ge=1, strict=True)
    profile: ProfileRef
    idempotency_key: str = Field(pattern=r'^[A-Za-z0-9_-]{16,64}$')
    target_shots: int = Field(default=8, ge=1, le=30, strict=True)
    aspect_ratio: Literal['16:9', '9:16', '1:1'] = '16:9'
    visual_style: str = Field(default='', max_length=2000)
    instructions: str = Field(default='', max_length=3000)
    reasoning_effort: EffortChoice = 'default'
