"""Closed assistant capabilities. Read snapshots and delegate writes to existing services."""
from copy import deepcopy
import json
import os

from pydantic import ValidationError

from app.domain import CreateProject, ResumeProject
from app.production.contracts import GenerateStoryboard, ReviseStoryboard, ModelConfig
from app.production.editing_contracts import TimelineRequest, ExportRequest
from app.production.editing_service import EditingService
from app.production.generation import StoryboardGenerator
from app.production.inspection import InspectionService
from app.production.inspection_contracts import CreateInspection
from app.production.media_contracts import CreateMediaRun, SelectMedia
from app.production.media_service import MediaService
from app.production.planning import digest
from app.production.reasoning import choose_effort
from app.production.review_contracts import ReviewRequest
from app.production.reviews import StoryboardReviewer
from app.production.video_runtime import VideoRuntime


KINDS = {
    'writer_create': CreateProject, 'writer_choose': ResumeProject,
    'writer_revise': ResumeProject, 'writer_clarify': ResumeProject,
    'storyboard_generate': GenerateStoryboard, 'storyboard_revise': ReviseStoryboard,
    'storyboard_review': ReviewRequest, 'image_generate': CreateMediaRun,
    'image_select': SelectMedia, 'video_select': SelectMedia,
    'video_inspect': CreateInspection, 'timeline_save': TimelineRequest, 'export_create': ExportRequest,
}
TITLES = dict(zip(KINDS, ('创建故事', '选择故事方向', '修订故事', '澄清并复审', '生成分镜',
    '保存分镜修订', '审核文字分镜', '生成镜头静态帧', '选用图片', '选用视频', '提取视频检查证据',
    '保存时间线', '创建成片导出')))
MODEL_KINDS = {'writer_create', 'writer_choose', 'writer_revise', 'writer_clarify',
               'storyboard_generate', 'storyboard_review', 'image_generate'}
BOARD_KINDS = set(KINDS) - {'writer_create', 'writer_choose', 'writer_revise', 'writer_clarify', 'storyboard_generate'}
RUN_KINDS = {'image_select', 'video_select', 'video_inspect'}
PLACEHOLDER_KEY = 'assistant_preview_only'


def _pick(value, fields):
    return {key: deepcopy(value[key]) for key in fields if key in value}


def _compact(value, limit=2000):
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [_compact(item, limit) for item in value[:30]]
    if isinstance(value, dict):
        return {key: _compact(item, limit) for key, item in value.items()}
    return value


def _diff(old, new, path=''):
    changes = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            changes.extend(_diff(old.get(key), new.get(key), f'{path}.{key}' if path else key))
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            changes.extend(_diff(old[i] if i < len(old) else None, new[i] if i < len(new) else None, f'{path}[{i}]'))
    elif old != new:
        changes.append({'field': path, 'before': _compact(old, 200), 'after': _compact(new, 200)})
    return changes[:100]


class AssistantActions:
    def __init__(self, store, stories, storyboard_provider=None, review_provider=None):
        self.store, self.stories = store, stories
        self.generator = StoryboardGenerator(store, storyboard_provider)
        self.reviewer = StoryboardReviewer(store, review_provider)
        self.media = MediaService(store)
        self.video = VideoRuntime(store)
        self.inspections = InspectionService(store, runtime=self.video)
        self.editing = EditingService(store)

    def context(self, project_id, context_dict):
        stage = context_dict.get('stage', 'writer')
        if stage not in ('writer', 'storyboard', 'editing'):
            raise ValueError('未知工作台阶段')
        snapshot = {'project_id': project_id, 'stage': stage,
            'storyboard_id': context_dict.get('storyboard_id'), 'shot_key': context_dict.get('shot_key'),
            'selection': _compact(context_dict.get('selection'), 4000),
            'workspace_dirty': bool(context_dict.get('workspace_dirty', False)),
            'semantic_video_verified': False,
            'media_notice': '仅提供素材元数据；未读取图像、视频或声音内容，不能据此判断画面语义或质量。'}
        profiles = self.store.list_profiles()
        snapshot['profiles'] = [dict(_pick(item, ('id', 'version', 'current_version', 'executable')),
            **_pick(item['config'], ('name', 'purpose', 'adapter', 'model')),
            configured=not item['config']['api_key_env'] or bool(os.getenv(item['config']['api_key_env'])))
            for item in profiles]
        authority = {'project_id': project_id, 'stage': stage,
                     'selection': snapshot['selection'], 'shot_key': snapshot['shot_key'],
                     'storyboard_id': snapshot['storyboard_id'], 'workspace_dirty': snapshot['workspace_dirty'],
                     'profiles': snapshot['profiles']}
        if project_id:
            project = self.stories.get(project_id)
            authority['project'] = project
            state = _pick(project['state'], ('project_id', 'draft', 'original_story', 'version', 'reviewed_version',
                'mode', 'status', 'constraints', 'card', 'issues', 'directions', 'revision_count', 'stop_reason'))
            snapshot['project'] = {'state': state, 'interrupt': deepcopy(project.get('interrupt')),
                **_pick(project, ('calls_used', 'max_calls'))}
            boards = self.store.list_storyboards(project_id)
            snapshot['storyboards'] = [_pick(b, ('id', 'version', 'source_version', 'source_current',
                'source_confirmed', 'confirmed', 'confirmation_effective')) | {'title': b['content']['title']} for b in boards]
            authority['boards'] = boards
            if snapshot['storyboard_id']:
                board = self.store.get_storyboard(project_id, snapshot['storyboard_id'])
                snapshot['board'] = _pick(board, ('id', 'version', 'version_id', 'source_version', 'source_version_id',
                    'source_current', 'source_confirmed', 'confirmation_effective', 'content'))
                shot_key = snapshot['shot_key']
                if shot_key:
                    shots = [s for s in board['content']['shots'] if s['key'] == shot_key]
                    if not shots:
                        raise ValueError('当前分镜不存在所选镜头')
                    snapshot['selected_shot'] = shots[0]
                images = self.media.list(project_id, board['id'])
                videos = self.video.list(project_id, board['id'])
                editing = self.editing.list(project_id, board['id'])
                authority.update(images=images, videos=videos, editing=editing)
                snapshot['images'] = [_pick(row, ('id', 'shot_key', 'frame_role', 'version', 'status', 'selected', 'applicable', 'size'))
                                      for row in images['runs']]
                snapshot['videos'] = [_pick(row, ('id', 'shot_key', 'version', 'status', 'selected', 'applicable', 'duration_ms'))
                                      | {'metadata': _pick((row.get('output') or {}).get('metadata', {}),
                                          ('duration_ms', 'width', 'height', 'fps', 'has_audio'))} for row in videos['runs']]
                timeline = editing.get('timeline')
                snapshot['timeline'] = _pick(timeline, ('id', 'version', 'source_version', 'content', 'applicable')) if timeline else None
                snapshot['audio'] = [_pick(row, ('id', 'duration_ms')) for row in editing.get('audio', [])]
                snapshot['local_clips'] = [_pick(row, ('id', 'filename', 'duration_ms', 'status', 'applicable', 'metadata'))
                                           for row in editing.get('local_clips', [])]
        snapshot['fingerprint'] = digest(authority)
        if not project_id:
            kinds = ['writer_create']
        elif stage == 'writer':
            state = snapshot['project']['state']
            kinds = (['writer_choose'] if state.get('status') == 'awaiting_direction' else
                     ['writer_revise', 'writer_clarify'] if snapshot['project'].get('interrupt') else [])
        elif stage == 'editing':
            kinds = ['timeline_save', 'export_create'] if snapshot.get('board') else []
        else:
            kinds = ['storyboard_generate']
            if snapshot.get('board'):
                kinds += ['storyboard_revise', 'storyboard_review', 'image_generate']
                if snapshot.get('images'):
                    kinds.append('image_select')
                if snapshot.get('videos'):
                    kinds += ['video_select', 'video_inspect']
        snapshot['available_actions'] = [self._description(kind, snapshot) for kind in kinds]
        # Preserve authoritative digest even when long saved text needs truncation for model context.
        for limit in (1200, 600, 200, 60):
            if len(json.dumps(snapshot, ensure_ascii=False)) <= 24000:
                break
            for field in ('project', 'board', 'selected_shot', 'timeline', 'storyboards', 'images', 'videos', 'local_clips', 'audio'):
                if field in snapshot:
                    snapshot[field] = _compact(snapshot[field], limit)
            snapshot['truncated'] = True
        if len(json.dumps(snapshot, ensure_ascii=False)) > 24000:
            for field in ('board', 'timeline', 'images', 'videos', 'storyboards', 'local_clips'):
                snapshot.pop(field, None)
        if len(json.dumps(snapshot, ensure_ascii=False)) > 24000:
            raise ValueError('当前项目上下文超出安全长度，请缩小所选工作范围后重试')
        return snapshot

    def _description(self, kind, snapshot):
        schema = KINDS[kind].model_json_schema()
        # Exact existing JSON schema, including nested definitions; the routing fields
        # remain local IDs rather than URLs or filesystem paths.
        schema['properties'] = dict(schema['properties'])
        fields = list(schema['properties'])
        if kind in BOARD_KINDS:
            fields.insert(0, 'storyboard_id')
            schema['properties']['storyboard_id'] = {'type': 'string', 'const': snapshot.get('storyboard_id')}
        if kind in RUN_KINDS:
            fields.append('run_id')
            schema['properties']['run_id'] = {'type': 'string', 'minLength': 1, 'maxLength': 64}
        return {'kind': kind, 'title': TITLES[kind], 'params_fields': fields,
                'params_schema': schema,
                'request_schema': KINDS[kind].__name__,
                'scope': '当前项目与当前选中分镜；版本、省略的幂等键由服务端固定',
                'may_call_model': kind in MODEL_KINDS}

    @staticmethod
    def _pin(params, field, value):
        if field in params and params[field] != value:
            raise ValueError('建议引用的版本、暂停节点或作用范围已变化：' + field)
        params[field] = value

    def prepare(self, project_id, context_snapshot, proposal_dict):
        kind = proposal_dict.get('kind')
        if kind not in KINDS:
            raise ValueError('助手不支持此动作')
        snapshot = context_snapshot
        if snapshot.get('project_id') != project_id:
            raise ValueError('建议不能跨项目执行')
        if (project_id is None) != (kind == 'writer_create'):
            raise ValueError('此动作与当前项目范围不匹配')
        params = deepcopy(proposal_dict.get('params', {}))
        if not isinstance(params, dict):
            raise ValueError('动作参数必须为对象')
        reason, execution_model = '', None
        board = snapshot.get('board')
        state = snapshot.get('project', {}).get('state', {})
        stage = snapshot['stage']
        if kind.startswith('writer_') and stage != 'writer':
            reason = '请切换到编剧工作台后操作'
        elif kind in ('timeline_save', 'export_create') and stage != 'editing':
            reason = '请切换到后期工作台后操作'
        if snapshot.get('workspace_dirty'):
            reason = '工作区有未保存修改，请先保存或撤销，再刷新建议'
        if snapshot.get('truncated'):
            reason = '当前保存数据超过完整上下文长度；本次仅可讨论，请缩小范围后重新生成可执行建议'
        if kind in BOARD_KINDS:
            if not board:
                raise ValueError('请先选择当前项目的分镜')
            self._pin(params, 'storyboard_id', board['id'])
            if not board['source_current'] or not board['source_confirmed']:
                reason = '分镜来源需要当前已审核并由用户确认的剧本'
            if kind not in ('storyboard_revise', 'storyboard_review') and not board['confirmation_effective']:
                reason = '需要用户先确认当前分镜版本'
        if kind in ('writer_choose', 'writer_revise', 'writer_clarify'):
            action = kind.removeprefix('writer_')
            self._pin(params, 'action', action)
            self._pin(params, 'version', state['version'])
            interrupt = snapshot['project'].get('interrupt')
            if not interrupt:
                raise ValueError('当前故事没有可恢复的暂停节点')
            self._pin(params, 'interrupt_id', interrupt['id'])
            if params.get('accepted_issue_ids'):
                raise ValueError('助手不能代替用户接受审核问题')
            if action == 'choose' and (state['status'] != 'awaiting_direction' or params.get('direction_id') not in
                    {d['id'] for d in state.get('directions', [])}):
                raise ValueError('只能选择当前列出的故事方向')
        if kind == 'storyboard_generate':
            self._pin(params, 'source_version', state['version'])
            if state.get('status') != 'confirmed' or state.get('mode') == 'direct' or state.get('reviewed_version') != state['version']:
                reason = '需要用户先确认当前已审核的剧本版本'
        if kind in BOARD_KINDS - {'video_inspect', 'timeline_save', 'export_create'}:
            self._pin(params, 'expected_version', board['version'])
        if kind == 'timeline_save':
            self._pin(params, 'source_version', board['version'])
            self._pin(params, 'expected_version', (snapshot.get('timeline') or {}).get('version', 0))
            clips = {row['id']: row for row in snapshot.get('local_clips', [])}
            clips.update({row['id']: row for row in snapshot.get('videos', []) if row.get('selected')})
            content = params.get('content', {})
            if not isinstance(content, dict):
                raise ValueError('时间线内容必须为对象')
            for clip in content.get('clips', []):
                owned = clips.get(clip.get('run_id'))
                if not owned or not owned.get('applicable'):
                    raise ValueError('时间线素材不属于当前分镜的可用素材')
                if clip.get('end_ms', 0) > owned.get('duration_ms', 0):
                    raise ValueError('裁切区间超过实际素材时长')
            audio = {row['id'] for row in snapshot.get('audio', [])}
            if any(track.get('asset_id') not in audio for track in content.get('audio_tracks', [])):
                raise ValueError('音频素材不属于当前项目分镜')
        if kind == 'export_create':
            timeline = snapshot.get('timeline')
            if not timeline:
                raise ValueError('请先保存时间线')
            self._pin(params, 'expected_version', timeline['version'])
            if not timeline.get('applicable'):
                reason = '时间线来源或选用素材已变化，请先重新保存'
        if kind == 'image_generate':
            if snapshot.get('shot_key'):
                self._pin(params, 'shot_key', snapshot['shot_key'])
            if params.get('shot_key') not in {shot['key'] for shot in board['content']['shots']}:
                raise ValueError('镜头不属于当前分镜')
        if kind in RUN_KINDS:
            rows = snapshot.get('images' if kind == 'image_select' else 'videos', [])
            run = next((r for r in rows if r['id'] == params.get('run_id')), None)
            if not run or (snapshot.get('shot_key') and run['shot_key'] != snapshot['shot_key']):
                raise ValueError('素材不属于当前项目、分镜或所选镜头')
            if not run.get('applicable') or run['status'] != 'succeeded':
                reason = '需要当前分镜版本对应的成功素材'
        if kind == 'storyboard_revise' and not snapshot.get('truncated'):
            content = params.get('content', {})
            if not isinstance(content, dict):
                raise ValueError('分镜内容必须为对象')
            if content.get('scenes') != board['content']['scenes']:
                raise ValueError('场戏拆解已固定，调整场戏需要新建分镜')
            scenes = {s['key']: s['source_quote'] for s in content['scenes']}
            if any(s.get('source_quote', '') not in scenes.get(s.get('scene_key'), '') for s in content.get('shots', [])):
                raise ValueError('镜头来源引用不在当前固定场戏中')
        if kind in ('storyboard_generate', 'storyboard_review', 'image_generate'):
            purpose = {'storyboard_generate': 'text', 'storyboard_review': 'review', 'image_generate': 'image'}[kind]
            if 'profile' not in params:
                eligible = [p for p in snapshot['profiles'] if p['purpose'] == purpose and p['executable']]
                params['profile'] = {'profile_id': eligible[0]['id'], 'version': eligible[0]['version']} if eligible else {'profile_id': 'not_configured', 'version': 1}
            try:
                profile = self.store.get_profile(params['profile']['profile_id'], params['profile']['version'])
                config = ModelConfig.model_validate(profile['config'])
                adapters = ('openai_images', 'ark_seedream') if purpose == 'image' else ('openai_chat',)
                execution_model = {'profile_id': profile['id'], 'version': profile['version'], 'model': config.model,
                                   'purpose': config.purpose, 'adapter': config.adapter}
                if config.purpose != purpose or config.adapter not in adapters:
                    reason = '所选配置用途或适配器未接入此动作'
                if kind == 'image_generate' and (config.reasoning_protocol != 'none' or
                        any(v is not None for v in config.parameters.model_dump().values())):
                    reason = '图片配置不接受文本思考或生成参数'
                if kind != 'image_generate':
                    choose_effort(config, params.get('reasoning_effort', 'default'))
                provider = self.generator.provider if kind == 'storyboard_generate' else self.reviewer.provider
                if config.api_key_env and not os.getenv(config.api_key_env) and (kind == 'image_generate' or provider.__class__.__name__ == 'ChatPlanner'):
                    reason = '执行模型缺少所需密钥配置'
            except KeyError:
                reason = '未配置此动作所需的模型'
        if kind.startswith('writer_'):
            provider = self.stories.provider
            execution_model = {'adapter': provider.__class__.__name__, 'model': getattr(provider, 'model', os.getenv('DEEPSEEK_MODEL', 'deepseek-chat'))}
            if provider.__class__.__name__ == 'DeepSeekProvider' and not getattr(provider, 'key', '') and not (kind == 'writer_create' and params.get('mode') == 'direct'):
                reason = '编剧执行模型缺少所需密钥配置'
        request_params = deepcopy(params)
        if kind in BOARD_KINDS:
            request_params.pop('storyboard_id', None)
        if kind in RUN_KINDS:
            request_params.pop('run_id', None)
        schema = KINDS[kind]
        if 'idempotency_key' in schema.model_fields:
            request_params.setdefault('idempotency_key', PLACEHOLDER_KEY)
        try:
            validated = schema.model_validate(request_params)
        except ValidationError:
            raise ValueError('动作参数未通过现有业务契约校验') from None
        normalized = validated.model_dump(mode='json')
        if kind in BOARD_KINDS:
            normalized['storyboard_id'] = params['storyboard_id']
        if kind in RUN_KINDS:
            normalized['run_id'] = params['run_id']
        preview = {'params': _compact(normalized, 400)}
        if kind in ('storyboard_revise', 'timeline_save'):
            old = board['content'] if kind == 'storyboard_revise' else (snapshot.get('timeline') or {}).get('content', {})
            preview = {'changes': _diff(old, normalized['content'])}
        return {'kind': kind, 'title': str(proposal_dict.get('title') or TITLES[kind])[:200],
            'summary': str(proposal_dict.get('summary') or TITLES[kind])[:2000], 'params': normalized,
            'preview': preview, 'execution_model': execution_model,
            'may_call_model': kind in MODEL_KINDS and not (kind == 'writer_create' and normalized['mode'] == 'direct'),
            'available': not bool(reason), 'unavailable_reason': reason}

    def execute(self, project_id, proposal_dict, idempotency_key, reserved_project_id=None):
        kind = proposal_dict.get('kind')
        params = deepcopy(proposal_dict.get('params', {}))
        stage = 'writer' if kind and kind.startswith('writer_') else 'editing' if kind in ('timeline_save', 'export_create') else 'storyboard'
        snapshot = self.context(project_id, {'stage': stage, 'storyboard_id': params.get('storyboard_id')})
        prepared = self.prepare(project_id, snapshot, proposal_dict)
        if not prepared['available']:
            raise ValueError(prepared['unavailable_reason'])
        params = prepared['params']
        board_id, run_id = params.pop('storyboard_id', None), params.pop('run_id', None)
        if 'idempotency_key' in KINDS[kind].model_fields:
            params['idempotency_key'] = idempotency_key
        request = KINDS[kind].model_validate(params)
        if kind == 'writer_create':
            result = self.stories.create(request, project_id=reserved_project_id)
            project_id = result['id']
        elif kind.startswith('writer_'):
            result = self.stories.resume(project_id, request)
        elif kind == 'storyboard_generate':
            result = self.generator.generate(project_id, request)
            board_id = (result.get('board') or {}).get('id')
        elif kind == 'storyboard_revise':
            result = self.store.revise_storyboard(project_id, board_id, request)
        elif kind == 'storyboard_review':
            result = self.reviewer.review(project_id, board_id, request)
        elif kind == 'image_generate':
            result = self.media.create(project_id, board_id, request)
        elif kind in ('image_select', 'video_select'):
            service = self.media if kind == 'image_select' else self.video
            result = service.select(project_id, board_id, run_id, request.expected_version)
        elif kind == 'video_inspect':
            result = self.inspections.create(project_id, board_id, run_id, request)
        elif kind == 'timeline_save':
            result = self.editing.save(project_id, board_id, request)
        elif kind == 'export_create':
            result = self.editing.create_export(project_id, board_id, request)
        return {'project_id': project_id, 'stage': stage, 'storyboard_id': board_id, 'result': result}
