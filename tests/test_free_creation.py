from app.domain import CreateProject
from app.service import StoryService
from tests.test_story import FakeModel, card, issue, STORY

class Writer(FakeModel):
    def generate(self, task, payload, schema):
        if task == 'plan':
            self.calls.append(task)
            return {'outline':'小禾交出钥匙后，取回钥匙再开门。'}, {}
        if task == 'compose':
            self.calls.append(task)
            return {'draft':STORY, 'card':card()}, {}
        return super().generate(task,payload,schema)

def test_title_gets_written_before_review(database_url):
    model=Writer()
    with StoryService(database_url,model) as service:
        result=service.create(CreateProject(story='钥匙的故事',mode='free'))
        assert model.calls[:3] == ['plan','compose','review']
        assert result['state']['original_story']=='钥匙的故事'
        assert result['state']['draft']==STORY
        assert result['state']['status']=='awaiting_confirmation'

def test_repeated_problem_stops_loop(database_url):
    model=Writer([[issue()]])
    with StoryService(database_url,model) as service:
        result=service.create(CreateProject(story=STORY,mode='free'))
        assert result['state']['status']=='no_progress'
        assert result['state']['revision_count']==2
        assert result['state']['issues']

def test_free_can_repair_constraint_without_changing_user_requirement(database_url):
    problem=issue('constraint',False)
    model=Writer([[problem],[]])
    with StoryService(database_url,model) as service:
        result=service.create(CreateProject(story=STORY,mode='free'))
        assert result['state']['revision_count']==1
        assert result['state']['status']=='awaiting_confirmation'
