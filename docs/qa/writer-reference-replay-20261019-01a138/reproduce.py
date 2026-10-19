"""Three saved failures, one real repair per card; distinct from end-to-end trials."""
import json
import time
from pathlib import Path
from app.domain import Extraction
from app.evidence_refs import EvidenceContract
from app.provider import DeepSeekProvider
from app.prompts import PROMPT_VERSION

root=Path('docs/qa/writer-reference-replay-20261019-01a138');root.mkdir(exist_ok=False)
old=json.loads(Path('docs/qa/repeated-writer-20261019-01a138/run.json').read_text(encoding='utf-8'))
v6=json.loads(Path('docs/qa/writer-stability-20261019-01a138/run.json').read_text(encoding='utf-8'))
examples=[next(c for c in old['model_calls'] if c['trial']=='seedling-1' and c['task']=='compose'),
          next(c for c in v6['model_calls'] if c['trial']=='book-2' and c['task']=='compose'),
          next(c for c in old['model_calls'] if c['trial']=='book-3' and c['task']=='revise')]
ledger={'prompt_version':PROMPT_VERSION,'kind':'historical-failure-real-repair-only', 'max_calls':3,'calls':[]}
provider=DeepSeekProvider()
try:
    for example in examples:
        payload={**example['payload'],**example['result'],
                 'validation_feedback':'卡片的来源引用或字段不合格，请选择当前来源目录的编号，纠正完整卡片；不要重写或返回正文。'}
        contract=EvidenceContract(Extraction.model_json_schema(),payload)
        payload['evidence_catalog']=contract.catalog
        entry={'from_trial':example['trial'],'from_task':example['task'],'payload':payload};ledger['calls'].append(entry)
        start=time.monotonic()
        try:
            raw,usage=provider.generate('repair_card',payload,contract.schema)
            entry.update(raw=raw,usage=usage)
            resolved=Extraction.model_validate(contract.resolve(raw)).model_dump()
            entry['resolved']=resolved
            sources={'original':payload['original_story'],'user':payload['constraints']+'\n'+'\n'.join(payload['feedback_history'])}
            errors=[name for name,f in resolved['card'].items() if f['source'] in sources and (not f['evidence'] or f['evidence'] not in sources[f['source']])]
            entry.update(passed=not errors,quote_errors=errors,returned_draft='draft' in raw)
        except Exception as exc:
            entry.update(passed=False,error_type=type(exc).__name__,error=str(exc),usage=entry.get('usage',getattr(exc,'usage',{})))
        entry['seconds']=round(time.monotonic()-start,2)
        (root/'run.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in entry.items() if k not in ('raw','resolved','payload')},ensure_ascii=False),flush=True)
finally:
    provider.close()
