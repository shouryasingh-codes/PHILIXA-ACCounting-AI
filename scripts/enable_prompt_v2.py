"""Enable only prompt-package settings; preserve provider/authority settings."""
import json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
env=root/'.env';backup=root/'data'/'agent-prompt-flags-backup.json'
text=env.read_text(encoding='utf-8-sig')
changes={'PHILIXA_AGENT_PROMPT_VERSION':'v2','PHILIXA_AGENT_EXAMPLE_COUNT':'2'}
if not backup.exists():
    old={key:(match.group(1) if (match:=re.search(r'^'+key+r'=(.*)$',text,re.M)) else None) for key in changes}
    backup.write_text(json.dumps(old,indent=2),encoding='utf-8')
for key,value in changes.items():
    text=re.sub(r'^'+key+r'=.*\n?','',text,flags=re.M)
    text=text.rstrip()+'\n'+key+'='+value+'\n'
env.write_text(text,encoding='utf-8')
print('Prompt v2 enabled; 2 examples per request. Previous prompt flags backed up.')
