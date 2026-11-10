"""Read-only Groq /models diagnostic using stdlib, no inference or secrets output."""
import json
import os
from pathlib import Path
import urllib.request
import urllib.error
import sys


def main():
    values={}
    path=Path(__file__).resolve().parents[1]/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):continue
            key,value=line.split('=',1)
            if key.strip() in ('PHILIXA_AI_API_KEY','PHILIXA_GROQ_API_KEY'):
                values[key.strip()]=value.strip().strip('\"\'')
    key=os.getenv('PHILIXA_AI_API_KEY') or values.get('PHILIXA_AI_API_KEY') or os.getenv('PHILIXA_GROQ_API_KEY') or values.get('PHILIXA_GROQ_API_KEY')
    if not key:
        print(json.dumps({'key_present':False}));return
    no_auth='--no-auth' in sys.argv
    headers={'User-Agent':'Mozilla/5.0 (compatible; PhilixaAI/6.0)'}
    if not no_auth:headers['Authorization']='Bearer '+key
    request=urllib.request.Request('https://api.groq.com/openai/v1/models',headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=20) as response:
            data=json.load(response)
            print(json.dumps({'http_status':response.status,'gpt_oss_20b_listed':any(m.get('id')=='openai/gpt-oss-20b' for m in data.get('data',[])),
                'inference_calls':0}))
    except urllib.error.HTTPError as exc:
        text=exc.read(1000).decode('utf-8',errors='replace')
        import re
        try:error=json.loads(text).get('error',{})
        except ValueError:error={}
        codes={k:v for k,v in error.items() if k in ('type','code') and isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',v)} if isinstance(error,dict) else {}
        print(json.dumps({'http_status':exc.code,'access_denied':'access denied' in text.lower(),
            'cloudflare':'cloudflare' in text.lower(),'server':exc.headers.get('Server'),
            'content_type':exc.headers.get('Content-Type'),'provider_error_codes':codes,'inference_calls':0,
            'authenticated':not no_auth,'invalid_key_marker':'invalid_api_key' in text,
            'region_marker':any(v in text.lower() for v in ('country','region','location')),
            'generic_denial':text.strip() in ('{"error":"Access denied"}','{"error": "Access denied"}') }))
    except Exception as exc:
        print(json.dumps({'error_type':type(exc).__name__,'inference_calls':0}))


if __name__=='__main__':main()
