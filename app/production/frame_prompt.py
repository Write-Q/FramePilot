"""Deterministic static-frame packet; this is not a semantic quality assessor."""
import hashlib
import re

from app.production.contracts import StoryboardContent

WORKFLOW_VERSION = 'frame-prompt-1.0.0'
_TOONFLOW = 'https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/'
SOURCES = (
    _TOONFLOW + 'knowledge/imagePromptCraft.md#L10-L41',
    _TOONFLOW + 'knowledge/imagePromptCraft.md#L100-L111',
    _TOONFLOW + 'storyboardImages.md#L12-L47',
    'https://github.com/Forget-C/Jellyfish/blob/a9678194ddf2d9be3ccbe78d4287d87d5089e123/backend/app/chains/agents/shot_frame_prompt_agents.py#L105-L124',
)
_FOCUS = {'first': '首帧：保留已确认的起始瞬间。', 'key': '关键帧：表现已确认的代表性瞬间。',
          'last': '尾帧：表现已确认的结束状态。'}


def build_frame_prompt(content, shot_key, role, prompt_override=''):
    if role not in _FOCUS:
        raise ValueError('帧角色必须是 first、key 或 last')
    content = StoryboardContent.model_validate(content)
    shot = next((item for item in content.shots if item.key == shot_key), None)
    if shot is None:
        raise ValueError('分镜不存在')
    if not isinstance(prompt_override, str) or len(prompt_override) > 12000:
        raise ValueError('提示词覆盖无效')
    base = prompt_override.strip() or getattr(shot.frame_prompts, role)
    if not base:
        raise ValueError('请填写对应静态帧描述或本次提示词，不从运动动作推测画面')
    scene = next(item for item in content.scenes if item.key == shot.scene_key)
    lines = ['生成单张静态分镜图。' + _FOCUS[role], '画面：' + base,
             '场景：' + scene.title, '画幅：' + content.aspect_ratio]
    for name, value in [('人物', '、'.join(shot.characters)), ('景别', shot.shot_size),
                        ('机位角度', shot.camera_angle), ('构图', shot.composition),
                        ('画面方向', shot.screen_direction), ('已确认光照', shot.lighting),
                        ('视觉风格', content.visual_style)]:
        if value:
            lines.append(name + '：' + value)
    lines.append('仅按文字描述绘制，未提供参考图片。保留已描述的主体、道具与空间关系；不要增加画外字幕、水印或界面覆盖；场内必要文字按描述保留。')
    # Overrides are the complete user-reviewed execution prompt, including previews.
    prompt = prompt_override.strip() or '\n'.join(lines)
    if re.search(r'\{\{\s*ref\b|@图\s*\d|参考图\s*\d', prompt, re.IGNORECASE):
        raise ValueError('当前仅支持文生图，请移除未实际提供的图片引用标记')
    return {'prompt': prompt, 'manifest': {'workflow_version': WORKFLOW_VERSION, 'shot_key': shot_key,
            'frame_role': role, 'prompt_source': 'override' if prompt_override.strip() else 'frame_prompts.' + role,
            'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
            'reference_images': [], 'sources': list(SOURCES), 'validation': 'structure_only; visual_review_required'}}
