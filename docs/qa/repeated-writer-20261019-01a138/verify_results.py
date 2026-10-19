import json
import shutil
from pathlib import Path
root=Path('docs/qa/repeated-writer-20261019-01a138')
d=json.loads((root/'run.json').read_text(encoding='utf-8'))
assert d['finished'] and d['test_database_cleaned'] and len(d['trials'])==6
rows=[]
for t in d['trials']:
    calls=[c for c in d['model_calls'] if c['trial']==t['id']]
    revisions=[c for c in calls if c['task']=='revise']
    raw_exact=bool(revisions) and revisions[0].get('result',{}).get('draft')==t.get('expected_draft')
    row={k:t.get(k) for k in ('id','create_first_pass','compose_first_pass','first_draft_available','revise_first_pass','exact_local_edit','review_blocks_exact_edit','final_status','export_ok','new_app_read_ok','model_calls')}
    row['raw_revision_exact']=raw_exact if revisions else None
    row['errors']=[{'step':s['label'],'error':s['project']['state']['error']} for s in t['steps'] if s['project']['state'].get('error')]
    row['tokens']=sum(c.get('usage',{}).get('total_tokens',0) for c in calls)
    if t.get('first_draft_available'):
        first=(root/t['id']/'first-draft.md').read_text(encoding='utf-8')
        if t['id']=='book-2':
            quotes=['折角被压平，旧痕重新可见。','画面停在书与手指上，温暖收束。']
            row['false_positive_proof']={q:q in first for q in quotes}
            assert all(row['false_positive_proof'].values()) and raw_exact
        if t.get('exact_local_edit'):
            assert (root/t['id']/'final-draft.md').read_text(encoding='utf-8')==t['expected_draft']
    rows.append(row)
summary={'trials':rows,'call_count':len(d['model_calls']),'tokens':d['total_tokens'],
         'provider_returned_json':sum(c.get('ok',False) for c in d['model_calls']),
         'model_seconds':round(sum(c['seconds'] for c in d['model_calls']),2),
         'create_first_pass':sum(bool(t.get('create_first_pass')) for t in rows),
         'compose_first_pass':sum(bool(t.get('compose_first_pass')) for t in rows),
         'revision_attempted':sum(t['raw_revision_exact'] is not None for t in rows),
         'raw_revision_exact':sum(t['raw_revision_exact'] is True for t in rows),
         'persisted_revision_exact':sum(t.get('exact_local_edit') is True for t in rows),
         'confirmed':sum(t.get('final_status')=='confirmed' for t in rows),
         'quote_validation_failures':sum(len(t['errors']) for t in rows),
         'database_cleaned':d['test_database_cleaned']}
(root/'checks.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copyfile('.runtime/repeated_writer_eval_01a138.py',root/'reproduce.py')
shutil.copyfile(__file__,root/'verify_results.py')
print(json.dumps(summary,ensure_ascii=False,indent=2))
