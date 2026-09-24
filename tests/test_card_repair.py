from app.domain import CreateProject
from app.service import StoryService
from tests.test_story import FakeModel, card, STORY


class BrokenQuoteModel(FakeModel):
    def __init__(self, repair=True):
        super().__init__()
        self.repair = repair
        self.payloads = []

    def generate(self, task, payload, schema):
        if task != 'extract':
            return super().generate(task, payload, schema)
        self.calls.append(task)
        self.payloads.append(payload)
        result = card()
        quote = '不存在的引用'
        if self.repair and len(self.payloads) > 1:
            quote = '小禾把唯一的钥匙交给阿林。'
        result['characters'] = dict(text='小禾、阿林：交接钥匙的人物。', source='original', evidence=quote)
        return {'card': result}, {}


def test_bad_card_quote_gets_one_counted_repair(database_url):
    model = BrokenQuoteModel()
    with StoryService(database_url, model) as service:
        result = service.create(CreateProject(story=STORY))
        assert result['state']['status'] == 'awaiting_confirmation'
        assert result['calls_used'] == 3
        assert model.payloads[1]['validation_feedback']
        assert result['state']['card']['characters']['evidence'] in STORY


def test_repeated_bad_quote_stops_without_false_review(database_url):
    model = BrokenQuoteModel(repair=False)
    with StoryService(database_url, model) as service:
        result = service.create(CreateProject(story=STORY))
        assert result['state']['status'] == 'failed'
        assert result['calls_used'] == 2
        assert 'review' not in model.calls
        assert result['state']['reviewed_version'] == 0


def test_card_repair_cannot_bypass_budget(database_url):
    with StoryService(database_url, BrokenQuoteModel(), max_calls=1) as service:
        result = service.create(CreateProject(story=STORY))
        assert result['calls_used'] == 1
        assert result['state']['status'] == 'budget_exhausted'
