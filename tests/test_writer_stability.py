from copy import deepcopy

import pytest

from app.domain import CreateProject
from app.provider import ProviderError
from app.service import StoryService
from tests.test_story import FakeModel, STORY, card, issue, resume


class QuoteWriter(FakeModel):
    def __init__(self, broken_task, repair=True, network=False):
        super().__init__()
        self.broken_task = broken_task
        self.repair = repair
        self.network = network
        self.payloads = []

    def generate(self, task, payload, schema):
        self.payloads.append((task, deepcopy(payload)))
        if task == self.broken_task:
            self.calls.append(task)
            if self.network:
                raise ProviderError('连接失败')
            if task == 'review':
                problem = issue()
                problem['evidence'] = [{'source': 'draft', 'quote': '不存在的审核原文'}]
                return {'issues': [] if payload.get('validation_feedback') and self.repair else [problem]}, {'total_tokens': 10}
            broken = card()
            broken['actions'] = dict(text='动作总结', source='user', evidence='模型转述的要求')
            return {'card': broken, 'draft': STORY + '\n只追加这句。'}, {'total_tokens': 10}
        if task == 'repair_card':
            self.calls.append(task)
            fixed = card()
            if not self.repair:
                fixed['actions'] = dict(text='动作总结', source='user', evidence='仍然不存在')
            return {'card': fixed}, {'total_tokens': 10}
        return super().generate(task, payload, schema)


@pytest.mark.parametrize('task', ['compose', 'revise'])
def test_card_correction_preserves_candidate_draft(database_url, task):
    model = QuoteWriter(task)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY, mode='free' if task == 'compose' else 'collaborative'))
        if task == 'revise':
            p = resume(service, p, 'revise', '只追加这句。')
        assert p['state']['status'] == 'awaiting_confirmation'
        assert p['state']['draft'] == STORY + '\n只追加这句。'
        assert model.calls.count(task) == 1
        assert model.calls.count('repair_card') == 1
        repair = next(payload for name, payload in model.payloads if name == 'repair_card')
        assert repair['draft'] == p['state']['draft']
        assert 'actions' in repair['validation_feedback']
        assert any(c['status'] == 'invalid_evidence' and c['usage']['total_tokens'] == 10 for c in p['calls'])


def test_card_correction_is_bounded_and_keeps_saved_draft(database_url):
    model = QuoteWriter('revise', repair=False)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        failed = resume(service, p, 'revise', '只追加这句。')
        assert failed['state']['status'] == 'failed'
        assert failed['state']['draft'] == STORY
        assert failed['state']['version'] == 1
        assert '新稿未采用' in failed['state']['error']
        assert model.calls.count('repair_card') == 1
        assert model.calls.count('review') == 1
        assert len(service.versions(p['id'])) == 1


def test_correction_cannot_exceed_budget(database_url):
    with StoryService(database_url, QuoteWriter('compose'), max_calls=2) as service:
        p = service.create(CreateProject(story=STORY, mode='free'))
        assert p['state']['status'] == 'budget_exhausted'
        assert p['calls_used'] == 2
        assert p['state']['draft'] == STORY


def test_network_failure_does_not_trigger_card_correction(database_url):
    model = QuoteWriter('compose', network=True)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY, mode='free'))
        assert p['state']['status'] == 'failed'
        assert 'repair_card' not in model.calls


def test_review_quote_gets_one_counted_correction(database_url):
    model = QuoteWriter('review')
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'awaiting_confirmation'
        assert model.calls == ['extract', 'review', 'review']
        assert p['calls_used'] == 3
        assert p['calls'][1]['status'] == 'invalid_evidence'


def test_review_correction_cannot_turn_invalid_evidence_into_pass(database_url):
    model = QuoteWriter('review', repair=False)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        assert p['state']['status'] == 'failed'
        assert p['state']['reviewed_version'] == 0
        assert model.calls == ['extract', 'review', 'review']


def test_review_receives_exact_previous_draft_and_diff_after_restart(database_url):
    model = QuoteWriter('unused')
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        assert 'revision_context' not in model.payloads[-1][1]
        p = resume(service, p, 'revise', '请补充归还钥匙。')
        context = model.payloads[-1][1]['revision_context']
        assert context['previous_draft'] == STORY
        assert context['changes'] == [{'operation': 'insert', 'before_start': len(STORY), 'before_end': len(STORY),
                                       'after_start': len(STORY), 'after_end': len(p['state']['draft']),
                                       'before': '', 'after': '\n此前阿林已把钥匙还给小禾。'}]
    restored_model = QuoteWriter('unused')
    with StoryService(database_url, restored_model) as service:
        clarified = resume(service, service.get(p['id']), 'clarify', '保留当前设定。')
        assert restored_model.payloads[-1][1]['revision_context'] == context
        assert clarified['state']['draft'] == p['state']['draft']
        assert clarified['state']['version'] == p['state']['version']


def test_real_constraint_is_not_removed_by_revision_context(database_url):
    problem = issue('constraint', True)
    with StoryService(database_url, FakeModel([[], [problem]])) as service:
        p = service.create(CreateProject(story=STORY))
        p = resume(service, p, 'revise', '补充归还钥匙。')
        assert p['state']['status'] == 'awaiting_input'
        assert p['state']['issues'][0]['category'] == 'constraint'


def test_manual_retry_after_restart_only_repairs_card_not_candidate(database_url):
    model = QuoteWriter('revise', repair=False)
    with StoryService(database_url, model) as service:
        p = service.create(CreateProject(story=STORY))
        failed = resume(service, p, 'revise', '只追加这句。')
        assert failed['state']['status'] == 'failed'
    restored = QuoteWriter('revise', repair=True)
    with StoryService(database_url, restored) as service:
        recovered = service.retry(p['id'])
        assert recovered['state']['status'] == 'awaiting_confirmation'
        assert recovered['state']['draft'] == STORY + '\n只追加这句。'
        assert restored.calls == ['repair_card', 'review']
        assert recovered['state']['version'] == 2
