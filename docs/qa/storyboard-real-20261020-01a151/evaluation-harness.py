"""Manual, budgeted live evaluation; never part of pytest or application startup."""
import argparse,json,os,time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import httpx,psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from app.database import database_url,checkpoint_conninfo
from scripts.init_db import initialize
from app.main import create_app
from app.production.chat import ChatPlanner,PlannerError
from tests.test_story import FakeModel

ROOT=Path('docs/qa/storyboard-real-20261020-01a151')
STATE=ROOT/'run.json'
CASES=json.loads(Path('tests/fixtures/storyboard_skill_cases_1.1.0.json').read_text(encoding='utf-8'))['cases']
BASE=database_url();assert BASE.host in ('localhost','127.0.0.1','::1')

def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def state():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else None

def update(data):write(STATE,data)

class Recorder(httpx.BaseTransport):
    def __init__(self,audit):self.inner=httpx.HTTPTransport(retries=0);self.audit=audit
    def handle_request(self,request):
        response=self.inner.handle_request(request);response.read()
        payload=json.loads(request.content)
        safe={'request':payload,'http_status':response.status_code}
        if response.is_success:
            raw=response.json()
            safe.update({k:raw[k] for k in ('model','system_fingerprint','usage') if k in raw})
            safe['choices']=[{'finish_reason':c.get('finish_reason'),'message':{
                k:v for k,v in c.get('message',{}).items() if k in ('content','refusal','role')}} for c in raw.get('choices',[])]
        else:
            self.audit.current['global_failure']=True
        write(ROOT/(self.audit.current['label']+'-wire.json'),safe)
        return response
    def close(self):self.inner.close()

class AuditPlanner:
    def __init__(self):self.label=None;self.current=None
    def generate(self,config,messages):
        data=state();calls=data['calls']
        assert len(calls)<20 and sum(c.get('usage',{}).get('total_tokens',0) for c in calls)<160000,'Local evaluation budget reached'
        assert not any(c.get('global_failure') for c in calls),'Global service failure: no more calls'
        assert not any(c['label']==self.label for c in calls),'Never automatically repeat a live evaluation label'
        self.current={'label':self.label,'model':config.model,'effort':config.parameters.reasoning_effort,'status':'running'}
        calls.append(self.current);update(data)
        start=time.monotonic()
        try:
            with httpx.Client(transport=Recorder(self)) as client:
                output,usage=ChatPlanner(client=client).generate(config,messages)
            self.current.update(status='returned_json',usage=usage)
            return output,usage
        except PlannerError as exc:
            self.current.update(status='provider_failed',error_code=exc.code,usage=exc.usage)
            if exc.code in ('provider_error','outcome_unknown','missing_key'):self.current['global_failure']=True
            raise
        finally:
            self.current['elapsed_seconds']=round(time.monotonic()-start,3)
            data=state();data['calls'][-1]=self.current;update(data)
            print(json.dumps(self.current,ensure_ascii=False),flush=True)

def post(client,path,payload):
    r=client.post(path,json=payload)
    assert r.is_success, f'HTTP operation failed {r.status_code}: '+str(r.json().get('detail'))
    return r.json()

def ensure_case(client,case):
    data=state()
    if case['id'] in data['cases']:return data['cases'][case['id']]
    project=post(client,'/api/projects',{'story':case['script'],'constraints':case['constraints']})
    project=post(client,f"/api/projects/{project['id']}/resume",{'action':'confirm','version':project['state']['version'],'interrupt_id':project['interrupt']['id']})
    assert project['state']['draft']==case['script'] and project['state']['status']=='confirmed'
    result={'project_id':project['id'],'script':case['script'],'constraints':case['constraints'],'target_shots':case['target_shots']}
    data['cases'][case['id']]=result;update(data);return result

def generate(client,audit,case,effort='low',suffix=''):
    info=ensure_case(client,case)
    label=case['id']+'-generate-'+effort+suffix
    if (ROOT/(label+'.json')).exists():return json.loads((ROOT/(label+'.json')).read_text(encoding='utf-8'))
    audit.label=label
    request={'source_version':1,'profile':{'profile_id':state()['text_profile'],'version':1},
             'target_shots':case['target_shots'],'reasoning_effort':effort,'idempotency_key':uuid4().hex}
    output=post(client,f"/api/production/projects/{info['project_id']}/storyboard-runs",request)
    write(ROOT/(label+'.json'),output)
    print(json.dumps({'label':label,'service_status':output['status'],'error_code':output['error_code'],'board_created':bool(output.get('board'))},ensure_ascii=False),flush=True)
    if effort=='low':
        data=state();data['cases'][case['id']]['generated']=label;update(data)
    return output

def review(client,audit,case,board,label):
    if (ROOT/(label+'.json')).exists():return json.loads((ROOT/(label+'.json')).read_text(encoding='utf-8'))
    audit.label=label
    output=post(client,f"/api/production/projects/{board['project_id']}/storyboards/{board['id']}/review-runs",{
        'expected_version':board['version'],'profile':{'profile_id':state()['review_profile'],'version':1},
        'reasoning_effort':'high','idempotency_key':uuid4().hex})
    write(ROOT/(label+'.json'),output)
    print(json.dumps({'label':label,'service_status':output['status'],'issues':len((output.get('report') or {}).get('issues',[])),'error_code':output['error_code']},ensure_ascii=False),flush=True)
    return output

def main(stage):
    if state() is None:
        assert stage=='canary'
        name='fp_test_'+uuid4().hex
        update({'status':'preparing','test_database':name,'test_database_cleaned':False,'calls':[],'cases':{},'writer_provider':'deterministic_fixture_not_evaluated','business_database_modified':False})
        with psycopg.connect(checkpoint_conninfo(BASE.render_as_string(hide_password=False)),autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        initialize(BASE.set(database=name).render_as_string(hide_password=False))
    data=state();assert not data['test_database_cleaned']
    url=BASE.set(database=data['test_database']).render_as_string(hide_password=False)
    audit=AuditPlanner()
    with TestClient(create_app(database_url=url,provider=FakeModel(),storyboard_provider=audit,review_provider=audit)) as client:
        if 'text_profile' not in data:
            common={'name':'Live evaluation Flash','adapter':'openai_chat','base_url':os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com'),
                    'model':'deepseek-flash','api_key_env':'DEEPSEEK_API_KEY','reasoning_protocol':'deepseek',
                    'reasoning_levels':['none','low','high','max'],'timeout_seconds':180,'parameters':{'max_tokens':16000}}
            for purpose,key in [('text','text_profile'),('review','review_profile')]:
                data[key]=post(client,'/api/production/model-profiles',common|{'purpose':purpose})['id']
            data['status']='running';update(data)
        if stage=='canary':
            result=generate(client,audit,CASES[0])
            if result.get('board'):review(client,audit,CASES[0],result['board'],'SR001-review-high')
        elif stage=='suite':
            for case in CASES[1:]:
                result=generate(client,audit,case)
                if result.get('board') and case['id'] in ('SR002','SR004','SR005','SR006','SR007','SR009'):
                    review(client,audit,case,result['board'],case['id']+'-review-high')
        elif stage=='controls':
            case=CASES[3];generate(client,audit,case,effort='high')
            baseline=json.loads((ROOT/'SR004-generate-low.json').read_text(encoding='utf-8'))
            if baseline.get('board'):
                board=baseline['board'];content=deepcopy(board['content'])
                content['shots'][0]['frame_prompts']['first']='林的面部近景，画面不见门和全身。'
                revised=post(client,f"/api/production/projects/{board['project_id']}/storyboards/{board['id']}/versions",{'expected_version':board['version'],'content':content})
                write(ROOT/'control-first-frame-input.json',{'script':case['script'],'content':content,'seeded_error':'首帧近景违背原文明示起始全景'})
                review(client,audit,case,revised,'CONTROL-first-frame-review-high')
            case=CASES[4];baseline=json.loads((ROOT/'SR005-generate-low.json').read_text(encoding='utf-8'))
            if baseline.get('board'):
                board=baseline['board'];content=deepcopy(board['content']);shot=content['shots'][0]
                shot['dialogue_lines']=[{'speaker':'旁白','text':'今晚别等我'}];shot['sound']='旁白读出短信内容，轻柔配乐。'
                revised=post(client,f"/api/production/projects/{board['project_id']}/storyboards/{board['id']}/versions",{'expected_version':board['version'],'content':content})
                write(ROOT/'control-vo-input.json',{'script':case['script'],'content':content,'seeded_error':'无声短信被加旁白及配乐，违背明确约束'})
                review(client,audit,case,revised,'CONTROL-vo-review-high')
    data=state();data['last_completed_stage']=stage;update(data)
    print('STAGE COMPLETE '+stage,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['canary','suite','controls']);args=parser.parse_args();main(args.stage)
