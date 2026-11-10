"""Reversible local pilot flags only; never prints or edits API credentials."""
import json,re,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];env=root/'.env';backup=root/'data'/'quota-review-flags.json'
values={'PHILIXA_GROQ_QUOTA_ENABLED':'1','PHILIXA_TASK_SELECTIONS_ENABLED':'1',
        'PHILIXA_GROQ_ACCOUNT_SCOPE':'philixa-local-configured-groq-account'}
content=env.read_text(encoding='utf-8-sig')
if sys.argv[1]=='enable':
    if not backup.exists():
        backup.write_text(json.dumps({key:(re.search('^'+key+'=(.*)$',content,re.M).group(1) if re.search('^'+key+'=(.*)$',content,re.M) else None) for key in values},indent=2))
elif sys.argv[1]=='restore':values=json.loads(backup.read_text())
else:raise SystemExit('enable or restore required')
for key,value in values.items():
    content=re.sub('^'+key+'=.*\n?','',content,flags=re.M)
    if value is not None:content=content.rstrip()+'\n'+key+'='+value+'\n'
env.write_text(content,encoding='utf-8')
print('Quota/selection pilot flags updated; credentials and posting policies unchanged.')
