"""审核组包及证据存在性验证，不把引文存在当成语义判断已被证明。"""
import json
import re

from app.production.contracts import Shot, StoryboardContent
from app.production.planning import digest, load_skill_bundle
from app.production.review_contracts import ReviewReport

WORKFLOW_VERSION = 'storyboard-reviewer-1.1.0'


def build_review_packet(body, card, constraints, content):
    instructions, skills = load_skill_bundle('review_registry.json', {'storyboard_review': 'storyboard-review-1.1.0.md'})
    content = StoryboardContent.model_validate(content).model_dump(mode='json')
    content.pop('bindings', None)
    schema = ReviewReport.model_json_schema()
    messages = [{'role': 'system', 'content': '\n\n'.join(instructions) + '\nJSON Schema:\n' + json.dumps(schema, ensure_ascii=False)},
                {'role': 'user', 'content': json.dumps({'script': body, 'card': card, 'constraints': constraints,
                                                       'storyboard': content}, ensure_ascii=False)}]
    return {'messages': messages, 'manifest': {'workflow_version': WORKFLOW_VERSION, 'skills': skills,
            'prompt_sha256': digest(messages), 'schema_sha256': digest(schema)}}


def _shot_field(shot, field):
    # 只支持实际制作字段，不允许访问配置绑定或任意对象属性。
    if field in Shot.model_fields and isinstance(shot[field], (str, int)):
        return str(shot[field])
    if field in ('frame_prompts.first', 'frame_prompts.key', 'frame_prompts.last'):
        return shot['frame_prompts'][field.split('.')[1]]
    match = re.fullmatch(r'(dialogue_lines|action_beats)\.(\d+)\.(speaker|text|description|duration_ms)', field)
    if match:
        name, index, attribute = match.groups()
        allowed = {'dialogue_lines': ('speaker', 'text'), 'action_beats': ('description', 'duration_ms')}
        if attribute in allowed[name] and int(index) < len(shot[name]):
            value = shot[name][int(index)][attribute]
            if isinstance(value, (str, int)):
                return str(value)
    raise ValueError('证据字段不在允许的镜头文本范围')


def validate_evidence(report, content, body):
    content = StoryboardContent.model_validate(content).model_dump(mode='json')
    scenes = {scene['key']: scene for scene in content['scenes']}
    shots = {shot['key']: shot for shot in content['shots']}
    for issue in report.issues:
        if any(key not in shots for key in issue.shot_keys) or any(key not in scenes for key in issue.scene_keys):
            raise ValueError('问题定位不存在')
        for evidence in issue.evidence:
            if evidence.source == 'script':
                if evidence.key is not None or evidence.field != 'body':
                    raise ValueError('剧本证据只能定位固定正文')
                text = body
            elif evidence.source == 'scene':
                if (evidence.key not in scenes or evidence.field not in ('source_quote', 'title')
                        or not (evidence.key in issue.scene_keys or any(shots[k]['scene_key'] == evidence.key for k in issue.shot_keys))):
                    raise ValueError('场次证据与问题定位不一致')
                text = scenes[evidence.key][evidence.field]
            else:
                if evidence.key not in shots or evidence.key not in issue.shot_keys:
                    raise ValueError('镜头证据与问题定位不一致')
                text = _shot_field(shots[evidence.key], evidence.field)
            if evidence.quote not in text:
                raise ValueError('审核引文不在对应固定内容中')
