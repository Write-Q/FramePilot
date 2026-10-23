"""Validated video preparation and a provider-neutral asynchronous job contract.

No concrete provider or runtime is registered here. Poll success validates only
the transport contract, never video decodability, audio or visual quality.
"""
from dataclasses import dataclass
import hashlib
import json
from typing import Literal, Protocol, runtime_checkable

from app.production.contracts import ModelConfig, StoryboardContent

WORKFLOW_VERSION = 'video-input-1.0.0'
_SOURCE = 'https://github.com/HBAI-Ltd/Toonflow-app/blob/d2e94aca7b59659ff6b4ca15f03cf134ec7f0e1d/packages/skills/v118workflow/references/'
SOURCES = (_SOURCE + 'knowledge/videoPromptCraft.md#L3-L25',
           _SOURCE + 'knowledge/videoPromptCraft.md#L136-L147',
           _SOURCE + 'videoProduction.md#L6-L18',
           _SOURCE + 'videoProduction.md#L22-L44')


def _identifier(value):
    return (isinstance(value, str) and 0 < len(value) <= 1000
            and value == value.strip() and not any(ord(char) < 32 or ord(char) == 127 for char in value))


@dataclass(frozen=True)
class VideoSubmission:
    external_id: str

    def __post_init__(self):
        if not _identifier(self.external_id):
            raise ValueError('视频服务必须返回有效外部任务标识')


@dataclass(frozen=True)
class VideoPoll:
    status: Literal['pending', 'succeeded', 'failed']
    output: bytes | None = None
    mime_type: str | None = None

    def __post_init__(self):
        if self.status not in ('pending', 'succeeded', 'failed'):
            raise ValueError('视频查询状态无效')
        if self.status == 'succeeded':
            if not isinstance(self.output, bytes) or not self.output or self.mime_type not in ('video/mp4', 'video/webm'):
                raise ValueError('视频成功返回必须包含非空视频字节及支持的媒体类型')
        elif self.output is not None or self.mime_type is not None:
            raise ValueError('未成功的视频查询不能携带输出')


@runtime_checkable
class VideoAdapter(Protocol):
    """Submit once; persist external_id before polling. Never resubmit on timeout.

    A future concrete provider must validate its capabilities and securely obtain
    bounded bytes. The caller must validate actual media before accepting it.
    """

    def submit(self, config: ModelConfig, packet: dict, first_frame: bytes) -> VideoSubmission: ...

    def poll(self, config: ModelConfig, external_id: str) -> VideoPoll: ...


def build_video_input(board, shot_key, selected_image):
    """Build a single-shot first-frame packet from trusted, current store records."""
    if not isinstance(board, dict) or not isinstance(selected_image, dict):
        raise ValueError('缺少当前分镜或已选首帧')
    if (any(board.get(field) is not True for field in
            ('source_current', 'source_confirmed', 'confirmed', 'confirmation_effective'))
            or type(board.get('version')) is not int or board['version'] < 1
            or type(board.get('current_version')) is not int
            or board['version'] != board['current_version'] or not _identifier(board.get('version_id'))):
        raise ValueError('视频输入需要当前有效确认的分镜及来源')
    if (selected_image.get('selected') is not True or selected_image.get('status') != 'succeeded'
            or selected_image.get('frame_role') != 'first'
            or selected_image.get('storyboard_version_id') != board['version_id']
            or selected_image.get('shot_key') != shot_key
            or not _identifier(selected_image.get('id')) or not _identifier(selected_image.get('media_id'))
            or ('kind' in selected_image and selected_image['kind'] != 'image')
            or ('project_id' in selected_image and selected_image['project_id'] != board.get('project_id'))):
        raise ValueError('请先选用当前分镜版本、当前镜号的成功首帧图片')
    try:
        content = StoryboardContent.model_validate(board.get('content'))
    except (ValueError, TypeError):
        raise ValueError('分镜内容不符合视频输入契约') from None
    shot = next((item for item in content.shots if item.key == shot_key), None)
    if shot is None:
        raise ValueError('视频输入指定的镜头不存在')
    if not shot.video_prompt:
        raise ValueError('请先填写本镜视频运动提示词，不从静态图猜测动作')
    lines = ['视频运动意图：' + shot.video_prompt]
    if shot.camera_motion and shot.camera_motion not in shot.video_prompt:
        lines.append('镜头运动：' + shot.camera_motion)
    if content.visual_style:
        lines.append('已确认视觉风格：' + content.visual_style)
    if shot.dialogue_lines:
        lines.extend('对白（' + line.speaker + '）：' + line.text for line in shot.dialogue_lines)
    elif shot.dialogue:
        lines.append('已确认对白：' + shot.dialogue)
    if shot.sound:
        lines.append('已确认声音：' + shot.sound)
    prompt = '\n'.join(lines)
    first_frame = {'media_id': selected_image['media_id'], 'run_id': selected_image['id']}
    packet = {'prompt': prompt, 'duration_ms': shot.duration_ms, 'first_frame': first_frame}
    fingerprint = hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':')).encode('utf-8')).hexdigest()
    packet['manifest'] = {'workflow_version': WORKFLOW_VERSION, 'sources': list(SOURCES),
        'storyboard_version_id': board['version_id'], 'storyboard_version': board['version'],
        'shot_key': shot_key, 'input_mode': 'single_first_frame', 'duration_ms': shot.duration_ms,
        'first_frame': dict(first_frame), 'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
        'input_sha256': fingerprint, 'validation': 'input_contract_only; provider_and_media_validation_pending',
        'requires_audio_capability': bool(shot.dialogue_lines or shot.dialogue or shot.sound)}
    return packet
