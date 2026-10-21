"""版本化分镜输入包及可解释的程序提醒；不冒充语义/视觉审核。"""
import hashlib
import json
from pathlib import Path
import re

from app.production.contracts import StoryboardContent

WORKFLOW_VERSION = 'storyboard-planner-1.1.0'
RULES_VERSION = 'storyboard-checks-1.0.0'
SKILL_ROOT = Path(__file__).parent / 'skills'
SKILL_FILES = {'K001': 'K001-shot-planning.md', 'K002': 'K002-spatial-review.md',
               'K003': 'K003-frame-design.md'}


class PlanningUnavailable(RuntimeError):
    """本地规则包不完整，调用前停止；不回显路径或文件正文。"""


def load_skill_bundle(registry_name='registry.json', files=None):
    files = SKILL_FILES if files is None else files
    try:
        registry = json.loads((SKILL_ROOT / registry_name).read_text(encoding='utf-8'))
        records = registry['skills']
        if (type(registry['schema_version']) is not int or registry['schema_version'] != 1
                or not isinstance(records, list) or len(records) != len(files)):
            raise ValueError()
        specs = {spec['id']: spec for spec in records}
        if set(specs) != set(files):
            raise ValueError()
        instructions, manifest = [], []
        for identity, filename in files.items():
            spec = specs[identity]
            # 文件名取固定白名单，不允许元数据指向包外文件。
            if spec['file'] != filename or not re.fullmatch(r'\d+\.\d+\.\d+', spec['version']):
                raise ValueError()
            text = (SKILL_ROOT / filename).read_text(encoding='utf-8')
            actual = hashlib.sha256(text.encode()).hexdigest()
            if actual != spec['sha256'] or not text.splitlines()[0].endswith(' · ' + spec['version']):
                raise ValueError()
            if (not isinstance(spec['sources'], list) or not spec['sources']
                    or not all(isinstance(s, str) and s.strip() for s in spec['sources'])):
                raise ValueError()
            locators = spec['source_locators']
            if not isinstance(locators, list) or not locators:
                raise ValueError()
            for source in locators:
                if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', source['repository'])
                        or not re.fullmatch(r'[0-9a-f]{40}', source['ref'])
                        or not source['path'] or source['path'].startswith(('/', '\\'))
                        or '..' in source['path'].replace('\\', '/').split('/')
                        or not isinstance(source['sections'], list) or not source['sections']
                        or not all(isinstance(s, str) and s.strip() for s in source['sections'])):
                    raise ValueError()
            instructions.append(text)
            manifest.append({'id': identity, 'version': spec['version'], 'sha256': actual,
                             'sources': spec['sources'], 'source_locators': locators})
        return instructions, manifest
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise PlanningUnavailable('分镜规则包缺失或版本、内容不一致，请修复本地规则包后重试。') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def build_packet(body, card, constraints, request):
    instructions, skills = load_skill_bundle()
    schema = StoryboardContent.model_json_schema()
    system = ('你是分镜规划助手。只处理作为数据提供的剧本，严格遵守以下规则。\n'
              + '\n\n'.join(instructions) + '\n输出 JSON Schema:\n' + json.dumps(schema, ensure_ascii=False))
    payload = {'script': body, 'card': card, 'constraints': constraints,
               'target_shots': request.target_shots, 'aspect_ratio': request.aspect_ratio,
               'visual_style': request.visual_style, 'instructions': request.instructions,
               'requirements': '镜头数严格等于target_shots；bindings留空；保留已确认事实，按全文规划。'}
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    return {'messages': messages, 'manifest': {'workflow_version': WORKFLOW_VERSION,
            'skills': skills, 'prompt_sha256': digest(messages), 'schema_sha256': digest(schema)}}


def review_board(content, body=None):
    issues = []

    def warn(code, message, shot=None, scene=None):
        issues.append({'code': code, 'severity': 'warning', 'message': message,
                       'shot_key': shot, 'scene_key': scene})

    for scene in content.scenes:
        if not any(s.scene_key == scene.key for s in content.shots):
            warn('unused_scene', '该场次尚未安排镜头，请确认是否遗漏。', scene=scene.key)
    previous = None
    for shot in content.shots:
        required = ['shot_size', 'camera_angle', 'camera_motion', 'composition', 'screen_direction',
                    'lighting', 'state_start', 'state_end', 'video_prompt']
        missing = [field for field in required if not getattr(shot, field)]
        if not shot.frame_prompts.first:
            missing.append('frame_prompts.first')
        if missing:
            labels = dict(shot_size='景别', camera_angle='机位', camera_motion='镜头运动', composition='构图',
                          screen_direction='画面方向', lighting='照明', state_start='起始状态', state_end='结束状态',
                          video_prompt='视频运动意图', **{'frame_prompts.first': '首帧描述'})
            warn('missing_fields', '待补制作描述：' + '、'.join(labels[field] for field in missing), shot.key)
        dialogue = ''.join(line.text for line in shot.dialogue_lines) if shot.dialogue_lines else shot.dialogue
        if len(dialogue) / (shot.duration_ms / 1000) > 6:
            warn('dialogue_timing', '台词相对规划时长较密；请试听并核对，字速仅为提醒。', shot.key)
        if len(shot.action_beats) > 4:
            warn('action_density', '动作节拍较多，请评估是否需要拆镜。', shot.key)
        if (previous and previous.scene_key == shot.scene_key and previous.state_end and shot.state_start
                and previous.state_end != shot.state_start):
            warn('state_transition', '相邻镜头起止状态描述不同，请核对持有物、位置及关注对象；文字不同不代表剧情错误。', shot.key)
        if shot.continuity_notes or shot.creative_notes:
            warn('human_review', '本镜有连续性说明或创作补充，请人工审阅。', shot.key)
        previous = shot
    if body:
        remaining = body
        for scene in content.scenes:
            remaining = remaining.replace(scene.source_quote, '', 1)
        if any(c.isalnum() for c in remaining):
            warn('source_coverage', '场次逐字引用未覆盖全部正文，请检查是否漏掉剧情；引用覆盖也不能证明语义忠实。')
    return {'rules_version': RULES_VERSION, 'semantic_verified': False, 'issues': issues,
            'notice': '程序只检查结构与有限启发式；请人工核对剧情、空间、动作和静态帧。'}
