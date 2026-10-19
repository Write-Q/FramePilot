"""Three bounded real correction calls replaying retained bad cards, not end-to-end trials."""
import json
from pathlib import Path
from app.domain import Extraction
from app.prompts import PROMPT_VERSION
from app.provider import DeepSeekProvider

root=Path('docs/qa/writer-card-repair-exact-20261019-01a138');root.mkdir(exist_ok=False)
baseline=json.loads(Path('docs/qa/repeated-writer-20261019-01a138/run.json').read_text(encoding='utf-8'))
examples=[next(c for c in baseline['model_calls'] if c['trial']==trial and c['task']==task)
          for trial,task in [('seedling-1','compose'),('seedling-2','revise'),('book-3','revise')]]
ledger={'prompt_version':PROMPT_VERSION,'kind':'saved-bad-output-replay-real-correction-only','max_calls':3,'calls':[]}
provider=DeepSeekProvider()
try:
    for old in examples:
        payload={**old['payload'],**old['result'], 'validation_feedback':'卡片标为original/user的evidence不是对应材料的连续原文。请逐字核对全部维度，不能转述、拼接或省略。'}
        user = payload['constraints'] + '\n' + '\n'.join(payload['feedback_history'])
        for name, facet in payload['card'].items():
            if facet['source'] in ('original', 'user'):
                source = payload['original_story'] if facet['source'] == 'original' else user
                quote = facet['evidence']
                if not quote or quote not in source:
                    payload['validation_feedback'] = f'理解卡片的 {name} 来源引用不是对应材料中的连续原文：{quote!r}。请逐字引用，不拼接、不省略、不改写 evidence；text 仍应概括总结。'
                    break
        payload.pop('input_kind',None)
        entry={'from_trial':old['trial'],'from_task':old['task'],'payload':payload};ledger['calls'].append(entry)
        try:
            raw,usage=provider.generate('repair_card',payload,Extraction.model_json_schema())
            entry.update(raw=raw,usage=usage)
            result=Extraction.model_validate(raw).model_dump()
            user=payload['constraints']+'\n'+'\n'.join(payload['feedback_history'])
            errors=[]
            for name,facet in result['card'].items():
                if facet['source'] in ('original','user'):
                    source=payload['original_story'] if facet['source']=='original' else user
                    if not facet['evidence'] or facet['evidence'] not in source: errors.append(name)
            entry['quote_errors']=errors;entry['passed']=not errors
            entry['returned_draft']='draft' in raw
        except Exception as exc: entry.update(passed=False,error_type=type(exc).__name__)
        (root/'run.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in entry.items() if k not in ('payload','raw')},ensure_ascii=False),flush=True)
finally:
    provider.close()
