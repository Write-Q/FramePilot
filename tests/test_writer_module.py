from copy import deepcopy
import pytest
from app.domain import CreateProject, ResumeProject
from app.service import StoryService, Conflict
from tests.test_story import FakeModel, STORY, card, issue

class CreativeModel(FakeModel):
    def __init__(self, idea=False, reviews=None):
        super().__init__(reviews);self.idea=idea;self.payloads=[]
    def generate(self, task, payload, schema):
        self.payloads.append((task,deepcopy(payload)))
        if task=='extract':
            self.calls.append(task)
            return {'card':card(),'input_kind':'idea' if self.idea else 'complete'},{}
        if task=='brainstorm':
            self.calls.append(task)
            return {'directions':[{'title':'方向一','outline':'猫市长追逐光点引发误会。'},
                                  {'title':'方向二','outline':'猫邮差送错一封邀请信。'}]},{}
        if task=='compose':
            self.calls.append(task)
            return {'draft':STORY,'card':card()},{}
        return super().generate(task,payload,schema)

def reply(service,p,action,**kwargs):
    return service.resume(p['id'],ResumeProject(version=p['state']['version'],interrupt_id=p['interrupt']['id'],action=action,**kwargs))

def test_collaborative_idea_waits_for_direction_then_composes(tmp_path):
    model=CreativeModel(idea=True)
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story='猫文明',mode='collaborative'))
        assert p['state']['status']=='awaiting_direction'
        assert model.calls==['extract','brainstorm']
        with pytest.raises(Conflict): reply(s,p,'choose',direction_id='invented')
        p=reply(s,p,'choose',direction_id=p['state']['directions'][0]['id'])
        assert p['state']['draft']==STORY
        assert p['state']['version']==2
        assert p['state']['original_story']=='猫文明'
        assert len(s.versions(p['id']))==2

def test_adopt_and_replace_are_server_resolved_and_audited(tmp_path):
    a=issue();b=issue('creative');b['suggestion']='这是被替换的建议'
    model=CreativeModel(reviews=[[a,b],[]])
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story=STORY))
        ids=[x['id'] for x in p['state']['issues']]
        p=reply(s,p,'revise',decisions=[{'issue_id':ids[0],'choice':'adopt'},
            {'issue_id':ids[1],'choice':'replace','text':'只调整最后一句对白'}])
        payload=next(v for t,v in model.payloads if t=='revise')
        assert payload['revision_instructions'][0]['instruction']==a['suggestion']
        assert payload['revision_instructions'][1]['instruction']=='只调整最后一句对白'
        assert len(p['state']['decision_history'])==1
        assert p['state']['version']==2

def test_clarification_never_rewrites_even_in_free_mode(tmp_path):
    model=CreativeModel(reviews=[[issue(needs_user=True)],[]])
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story=STORY,mode='free'))
        old=p['state']['draft'];calls=p['calls_used']
        p=reply(s,p,'clarify',feedback='这是刻意保留的伏笔。')
        assert p['state']['draft']==old
        assert p['state']['version']==1
        assert p['state']['revision_count']==0
        assert p['calls_used']==calls+1

def test_unselected_problem_remains_and_unknown_decision_rejected(tmp_path):
    model=CreativeModel(reviews=[[issue(),issue('creative')],[]])
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story=STORY))
        with pytest.raises(Conflict):
            reply(s,p,'revise',decisions=[{'issue_id':'bad','choice':'adopt'}])
        p=reply(s,p,'revise',decisions=[{'issue_id':p['state']['issues'][1]['id'],'choice':'adopt'}])
        # 模型漏报不应使未处理问题被默认为接受。
        assert p['state']['issues']

def test_direct_entry_does_not_call_model(tmp_path):
    model=CreativeModel()
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story=STORY,mode='direct'))
        assert p['state']['status']=='ready_for_production'
        assert p['state']['draft']==STORY
        assert p['calls_used']==0

def test_direction_choice_survives_restart(tmp_path):
    with StoryService(tmp_path,CreativeModel(idea=True)) as s:
        p=s.create(CreateProject(story='猫文明'))
    with StoryService(tmp_path,CreativeModel()) as s:
        result=reply(s,p,'choose',direction_id=p['state']['directions'][1]['id'],feedback='保留温暖结尾')
        assert result['state']['outline']=='猫邮差送错一封邀请信。'
        assert result['state']['decision_history'][0]['feedback']=='保留温暖结尾'
        with pytest.raises(Conflict): reply(s,p,'choose',direction_id=p['state']['directions'][1]['id'])

def test_adopt_is_not_available_in_free_mode(tmp_path):
    with StoryService(tmp_path,CreativeModel(reviews=[[issue(needs_user=True)]])) as s:
        p=s.create(CreateProject(story=STORY,mode='free'))
        with pytest.raises(Conflict):
            reply(s,p,'revise',decisions=[{'issue_id':p['state']['issues'][0]['id'],'choice':'adopt'}])

def test_clarification_does_not_launch_free_loop_when_unresolved(tmp_path):
    model=CreativeModel(reviews=[[issue(needs_user=True)],[issue()]])
    with StoryService(tmp_path,model) as s:
        p=s.create(CreateProject(story=STORY,mode='free'))
        p=reply(s,p,'clarify',feedback='这里只解释背景，请保留正文。')
        assert p['state']['status']=='awaiting_input'
        assert p['state']['revision_count']==0
        assert 'revise' not in model.calls

def test_clarification_respects_persistent_budget(tmp_path):
    with StoryService(tmp_path,CreativeModel(reviews=[[issue()]]),max_calls=2) as s:
        p=s.create(CreateProject(story=STORY))
        with pytest.raises(Conflict): reply(s,p,'clarify',feedback='这是伏笔')
        assert s.get(p['id'])['calls_used']==2

def test_replacement_requires_text_and_clarify_rejects_adopt():
    from pydantic import ValidationError
    for action, decision in [('revise',{'issue_id':'x','choice':'replace'}),('clarify',{'issue_id':'x','choice':'adopt'})]:
        with pytest.raises(ValidationError):
            ResumeProject(version=1,interrupt_id='x',action=action,decisions=[decision])
