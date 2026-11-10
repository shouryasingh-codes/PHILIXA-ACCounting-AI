"""Reversible local review acceptance flags; never changes keys or posting policy."""
import json,re,sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
path=root/'.env'
evidence=root/'data'/'task-agent-review-flags.json'
keys={'PHILIXA_TASK_AGENT_ENABLED':'1','PHILIXA_TASK_AGENT_BILLING_MODE':'free',
      'PHILIXA_GROQ_FREE_TIER_CONFIRMED':'1','PHILIXA_TASK_AGENT_REVIEW_ONLY':'1'}
text=path.read_text(encoding='utf-8-sig')
if sys.argv[1]=='enable':
    if evidence.exists():raise SystemExit('Review flag backup already exists; inspect before enabling again.')
    old={key:(re.search(r'^'+key+r'=(.*)$',text,re.M).group(1) if re.search(r'^'+key+r'=(.*)$',text,re.M) else None) for key in keys}
    evidence.write_text(json.dumps(old,indent=2),encoding='utf-8')
    changes=keys
elif sys.argv[1]=='restore':changes=json.loads(evidence.read_text(encoding='utf-8'))
else:raise SystemExit('enable or restore required')
for key,value in changes.items():
    text=re.sub(r'^'+key+r'=.*\n?', '',text,flags=re.M)
    if value is not None:text=text.rstrip()+'\n'+key+'='+value+'\n'
path.write_text(text,encoding='utf-8')
print('Local task-agent review flags updated; keys and posting policies unchanged.')
