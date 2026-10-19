"""Bounded actual model evaluation; no fake provider and no production changes."""
import difflib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from app.database import database_url, checkpoint_conninfo
from app.main import create_app
from app.provider import DeepSeekProvider, ProviderError
from app.prompts import PROMPT_VERSION
from scripts.init_db import initialize

ROOT=Path('docs/qa/writer-stability-final-20261019-01a138')
ROOT.mkdir(parents=True,exist_ok=False)
ledger={'started_at':datetime.now(timezone.utc).isoformat(),'prompt_version':PROMPT_VERSION,
        'max_real_calls':10,'model_calls':[],'trials':[],'finished':False}
active=None
def save():
    (ROOT/'run.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
class ObservedProvider(DeepSeekProvider):
    def generate(self,task,payload,schema):
        if len(ledger['model_calls'])>=10: raise ProviderError('本批测试达到调用上限')
        entry={'trial':active['id'],'task':task,'payload':payload}
        ledger['model_calls'].append(entry);save();start=time.monotonic()
        try:
            result,usage=super().generate(task,payload,schema)
            entry.update(ok=True,result=result,usage=usage)
            return result,usage
        except Exception as exc:
            entry.update(ok=False,error_type=type(exc).__name__);raise
        finally:
            entry['seconds']=round(time.monotonic()-start,2);save()
            print(json.dumps({'trial':active['id'],'call':len(ledger['model_calls']),'task':task,'ok':entry.get('ok')},ensure_ascii=False),flush=True)
def post(client,label,path,body):
    response=client.post(path,json=body)
    step={'label':label,'request':body,'http_status':response.status_code}
    active['steps'].append(step)
    if response.status_code not in (200,201):
        step['response']=response.json();save();raise RuntimeError('HTTP rejection')
    if 'text/event-stream' in response.headers.get('content-type',''):
        events=[json.loads(s[6:]) for s in response.text.splitlines() if s.startswith('data: ')]
        step['events']=[e for e in events if e['event']!='delta']
        results=[e['data'] for e in events if e['event']=='result']
        if not results: save();raise RuntimeError('No final result')
        project=results[-1]
    else: project=response.json()
    step['project']=project;active['final_project']=project;save()
    folder=ROOT/active['id']
    (folder/(label+'.json')).write_text(json.dumps(project,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'trial':active['id'],'step':label,'status':project['state']['status'],'calls':project['calls_used']},ensure_ascii=False),flush=True)
    return project
def resume(project,action,**kwargs):
    return dict(version=project['state']['version'],interrupt_id=project['interrupt']['id'],action=action,**kwargs)
def blocking(p): return [i for i in p['state']['issues'] if i['needs_user'] or i['category']=='constraint']
cases=[
 {'id':'seedling','story':'雨后的小支架','person':'小禾','addition':'小禾用指尖轻轻拢紧幼苗根部的湿土。',
  'constraints':'30秒写实短片；唯一人物小禾，唯一地点自家院子；主线是扶正幼苗；无对白、无画外音、无魔法，不增加新人物或第二地点；结尾温暖。剧本按4个编号镜头段落输出，每段含大致秒数和可见动作，合计30秒。不要另列片名、创作说明或备选结尾。'},
 {'id':'book','story':'旧书的新封面','person':'小宁','addition':'小宁用指腹轻轻压平书脊上的纸边。',
  'constraints':'30秒写实短片；唯一人物小宁，唯一地点家里的书桌旁；主线是给旧书包上新书皮；无对白、无画外音、无魔法，不增加新人物或第二地点；结尾温暖。剧本按4个编号镜头段落输出，每段含大致秒数和可见动作，合计30秒。不要另列片名、创作说明或备选结尾。'}]
ledger['cases']=cases
base=database_url();assert base.host in ('localhost','127.0.0.1','::1')
name='fp_eval_'+uuid4().hex;ledger['database_name']=name;save()
with psycopg.connect(checkpoint_conninfo(base.render_as_string(hide_password=False)),autocommit=True) as connection:
    connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
target=base.set(database=name).render_as_string(hide_password=False)
try:
    initialize(target)
    # Alternate cases to reduce confounding from a change in service conditions.
    for repeat in range(1,2):
        for case in cases[:1]:
            active={'id':case['id']+'-'+str(repeat),'case':case['id'],'repeat':repeat,'steps':[]}
            ledger['trials'].append(active);folder=ROOT/active['id'];folder.mkdir();save()
            provider=ObservedProvider();assert provider.key
            ledger['model']=provider.model
            try:
                with TestClient(create_app(database_url=target,provider=provider)) as client:
                    p=post(client,'01-create','/api/projects/stream',dict(story=case['story'],mode='collaborative',constraints=case['constraints']))
                    active['create_first_pass']=p['state']['status']=='awaiting_direction'
                    if p['state']['status']=='failed': p=post(client,'01b-retry',f"/api/projects/{p['id']}/retry/stream",{})
                    if p['state']['status']!='awaiting_direction': raise RuntimeError('No direction pause')
                    chosen=p['state']['directions'][0];active['chosen_direction']=chosen
                    p=post(client,'02-compose',f"/api/projects/{p['id']}/resume/stream",resume(p,'choose',direction_id=chosen['id'],feedback='保留这条方向，重点用可见动作表现，不新增对白和人物。'))
                    active['compose_first_pass']=p['state']['status']!='failed' and bool(p.get('interrupt'))
                    if p['state']['status']=='failed': p=post(client,'02b-retry',f"/api/projects/{p['id']}/retry/stream",{})
                    if not p.get('interrupt') or not p['state']['draft'] or p['state']['status']=='failed': raise RuntimeError('No usable first draft')
                    active['first_draft_available']=True
                    first=p['state']['draft'];(folder/'first-draft.md').write_text(first,encoding='utf-8')
                    candidates=[s for s in first.splitlines() if len(s.strip())>=15]
                    if not candidates: raise RuntimeError('No target line')
                    line=candidates[min(1,len(candidates)-1)];addition=case['addition'];expected=first.replace(line,line+addition,1)
                    active['expected_draft']=expected
                    instruction='本轮只做一处局部改动：在下列这一行的末尾追加“'+addition+'”。\n目标行原文：'+line+'\n不要调整其他任何行，其他段落、编号、秒数、标点和换行逐字保持原样；不额外执行审核中的其他创作建议。'
                    p=post(client,'03-revise',f"/api/projects/{p['id']}/resume/stream",resume(p,'revise',feedback=instruction))
                    active['revise_first_pass']=p['state']['status']!='failed'
                    active['exact_local_edit']=p['state']['draft']==expected
                    active['review_blocks_exact_edit']=active['exact_local_edit'] and bool(blocking(p))
                    active['issues_after_revision']=p['state']['issues']
                    (folder/'revision.diff').write_text(''.join(difflib.unified_diff(first.splitlines(keepends=True),p['state']['draft'].splitlines(keepends=True),fromfile='first',tofile='revised')),encoding='utf-8')
                    if active['review_blocks_exact_edit'] and p.get('interrupt') and p['state']['status']!='failed' and p['calls_used']<10:
                        before=p['state']['draft'];version=p['state']['version']
                        clarification='仅澄清，不修改正文：程序逐字比较证实当前正文恰好等于首稿在指定目标行末尾追加“'+addition+'”，其余字符及换行均未改变。新增句前没有新增换行。请对照当前 draft、上一轮修改要求与原始创作约束重新审核；如果仍有真实约束冲突，请保留并具体说明，不必为确认而放行。'
                        p=post(client,'04-clarify',f"/api/projects/{p['id']}/resume/stream",resume(p,'clarify',feedback=clarification))
                        active['clarify_preserved_draft_version']=before==p['state']['draft'] and version==p['state']['version']
                    if p.get('interrupt') and p['state']['status']!='failed' and not blocking(p) and p['state']['reviewed_version']==p['state']['version']:
                        p=post(client,'05-confirm',f"/api/projects/{p['id']}/resume/stream",resume(p,'confirm',accepted_issue_ids=[i['id'] for i in p['state']['issues']]))
                    active['final_status']=p['state']['status'];active['project_id']=p['id']
                    (folder/'final-draft.md').write_text(p['state']['draft'],encoding='utf-8')
                    exported=client.get(f"/api/projects/{p['id']}/export")
                    active['export_ok']=exported.status_code==200 and p['state']['draft'] in exported.text
                    (folder/'export.md').write_text(exported.text,encoding='utf-8')
                    active['versions']=client.get(f"/api/projects/{p['id']}/versions").json()
                with TestClient(create_app(database_url=target,provider=DeepSeekProvider())) as client:
                    restored=client.get(f"/api/projects/{active['project_id']}").json()
                    active['new_app_read_ok']=restored['state']==active['final_project']['state']
            except Exception as exc:
                active['error_type']=type(exc).__name__
                active['error']=str(exc) if isinstance(exc,RuntimeError) else 'Probe failed; inspect saved stages'
                if active.get('final_project'): active['final_status']=active['final_project']['state']['status']
            active['model_calls']=sum(c['trial']==active['id'] for c in ledger['model_calls']);save()
            print('TRIAL_DONE '+json.dumps({k:v for k,v in active.items() if k not in ('steps','expected_draft','final_project','chosen_direction','versions','issues_after_revision')},ensure_ascii=False),flush=True)
    ledger['finished']=True
finally:
    ledger['total_tokens']=sum(c.get('usage',{}).get('total_tokens',0) for c in ledger['model_calls'])
    save()
    # Only this task's exact generated local database; never touch the business DB.
    assert name==ledger['database_name'] and name.startswith('fp_eval_') and len(name)==40 and base.database!=name
    with psycopg.connect(checkpoint_conninfo(base.render_as_string(hide_password=False)),autocommit=True) as connection:
        connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        ledger['test_database_cleaned']=connection.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone() is None
    save()
    print('BATCH_DONE '+json.dumps({'finished':ledger['finished'],'calls':len(ledger['model_calls']),'tokens':ledger['total_tokens'],'cleaned':ledger.get('test_database_cleaned')},ensure_ascii=False),flush=True)
