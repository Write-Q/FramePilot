from copy import deepcopy

import pytest

from app.domain import CreateProject, ResumeProject
from app.service import StoryService, Conflict
from app.provider import ProviderError


STORY = '小禾把唯一的钥匙交给阿林。小禾随后用这把钥匙打开门。'


def card():
    return {name: {'text': '未说明', 'source': 'unknown', 'evidence': ''} for name in
            ['theme', 'characters', 'plot', 'props', 'scenes', 'actions', 'camera', 'visual_style', 'sound', 'pacing']}


def issue(category='continuity', needs_user=False):
    return {'category': category, 'description': '钥匙归属存在疑点',
            'evidence': [{'source': 'draft', 'quote': '唯一的钥匙交给阿林'},
                         {'source': 'draft', 'quote': '小禾随后用这把钥匙打开门'}],
            'suggestion': '补充取回钥匙的事件', 'needs_user': needs_user}


class FakeModel:
    def __init__(self, reviews=None, fail=False):
        self.reviews = reviews or [[]]
        self.calls = []
        self.fail = fail

    def generate(self, task, payload, schema):
        self.calls.append(task)
        if self.fail:
            raise ProviderError('测试中的连接失败')
        if task == 'plan':
            return {'outline':'测试故事骨架'}, {'total_tokens':10}
        if task == 'compose':
            return {'draft':payload['original_story'], 'card':card()}, {'total_tokens':10}
        if task == 'extract':
            return {'card': card()}, {'total_tokens': 10}
        if task == 'review':
            items = self.reviews.pop(0) if len(self.reviews) > 1 else self.reviews[0]
            return {'issues': deepcopy(items)}, {'total_tokens': 10}
        return {'draft': payload['draft'] + '\n此前阿林已把钥匙还给小禾。', 'card': card()}, {'total_tokens': 10}


def resume(service, project, action='confirm', feedback='', accepted=None):
    return service.resume(project['id'], ResumeProject(
        version=project['state']['version'], interrupt_id=project['interrupt']['id'],
        action=action, feedback=feedback, accepted_issue_ids=accepted or []))


def test_clean_story_waits_for_confirmation(tmp_path):
    model = FakeModel()
    with StoryService(tmp_path, model) as service:
        project = service.create(CreateProject(story=STORY))
        assert project['state']['status'] == 'awaiting_confirmation'
        assert project['calls_used'] == 2
        done = resume(service, project)
        assert done['state']['status'] == 'confirmed'
        assert done['state']['stop_reason'] == '当前版本已由用户确认。'
        assert done['state']['original_story'] == STORY
        assert model.calls == ['extract', 'review']


@pytest.mark.parametrize('mode', ['faithful', 'collaborative'])
def test_non_free_mode_does_not_rewrite_without_user(tmp_path, mode):
    model = FakeModel([[issue()]])
    with StoryService(tmp_path, model) as service:
        project = service.create(CreateProject(story=STORY, mode=mode))
        assert project['state']['status'] == 'awaiting_input'
        assert 'revise' not in model.calls


def test_free_mode_stops_at_three_revisions(tmp_path):
    problems = []
    for quote in ['小禾', '钥匙', '阿林', '打开门']:
        problem = issue(); problem['evidence'] = [{'source':'original','quote':quote}]
        problems.append([problem])
    model = FakeModel(problems)
    with StoryService(tmp_path, model) as service:
        project = service.create(CreateProject(story=STORY, mode='free'))
        assert project['state']['revision_count'] == 3
        assert project['state']['status'] == 'limit_reached'
        assert model.calls.count('revise') == 3
        assert project['state']['issues']
        assert len(service.versions(project['id'])) == 4


def test_free_mode_constraints_pause(tmp_path):
    with StoryService(tmp_path, FakeModel([[issue('constraint', True)]])) as service:
        project = service.create(CreateProject(story=STORY, mode='free'))
        assert project['state']['status'] == 'awaiting_input'
        with pytest.raises(Conflict):
            resume(service, project, accepted=[p['id'] for p in project['state']['issues']])


def test_resume_after_restart_and_replay_rejected(tmp_path):
    with StoryService(tmp_path, FakeModel([[issue()]])) as service:
        project = service.create(CreateProject(story=STORY))
    with StoryService(tmp_path, FakeModel()) as service:
        updated = resume(service, project, 'revise', '请补充阿林归还钥匙，再开门。')
        assert updated['state']['version'] == 2
        assert updated['state']['revision_count'] == 1
        assert updated['calls_used'] == 4
        with pytest.raises(Conflict):
            resume(service, project)
        assert resume(service, updated)['state']['status'] == 'confirmed'


def test_call_limit_survives_pause(tmp_path):
    with StoryService(tmp_path, FakeModel([[issue()]]), max_calls=3) as service:
        project = service.create(CreateProject(story=STORY, mode='free'))
        assert project['state']['status'] == 'budget_exhausted'
        with pytest.raises(Conflict):
            resume(service, project, 'revise', '请修订')
        assert service.get(project['id'])['calls_used'] == 3


def test_provider_failure_is_not_success(tmp_path):
    with StoryService(tmp_path, FakeModel(fail=True)) as service:
        project = service.create(CreateProject(story=STORY))
        assert project['state']['status'] == 'failed'
        assert project['calls_used'] == 1
        assert not project['interrupt']


def test_fabricated_evidence_rejected(tmp_path):
    invalid = issue()
    invalid['evidence'][0]['quote'] = '原文根本没有这句话'
    with StoryService(tmp_path, FakeModel([[invalid]])) as service:
        project = service.create(CreateProject(story=STORY))
        assert project['state']['status'] == 'failed'


def test_acknowledgement_is_explicit(tmp_path):
    with StoryService(tmp_path, FakeModel([[issue()]])) as service:
        project = service.create(CreateProject(story=STORY))
        with pytest.raises(Conflict):
            resume(service, project)
        ids = [item['id'] for item in project['state']['issues']]
        assert resume(service, project, accepted=ids)['state']['status'] == 'confirmed'

