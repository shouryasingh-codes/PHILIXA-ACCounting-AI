"""Read-only installed Tally probe. Writes a sanitized acceptance record, never accounting rows."""
import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['PHILIXA_TALLY_HOST']='127.0.0.1'
from app.services.tally_connector import local_operation
from app.services.tally_mcp import CONTRACTS,PIN
from app.services.tally_mcp_reports import display
from helper.mcp_runtime import execute_read

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--company',required=True)
    parser.add_argument('--output',default='data/mcp-live-reports.json');options=parser.parse_args()
    companies=asyncio.run(local_operation('discover',port=9000))['companies']
    selected=[c for c in companies if c['name']==options.company]
    if len(selected)!=1:raise SystemExit('Requested company unavailable/ambiguous.')
    today=datetime.now(ZoneInfo('Asia/Kolkata')).date()
    stamp=today.strftime('%d-%m-%Y')
    results=[]
    for tool,contract in CONTRACTS.items():
        if contract['category']!='read':continue
        args={k:stamp for k in contract['inputSchema'].get('required',[]) if k in ('from','to','asOf')}
        if 'ledgerName' in contract['inputSchema'].get('required',[]):
            # Exact conventional ledger is a test input, not a financial inference.
            args['ledgerName']='Cash'
        try:
            raw=execute_read(ROOT/'integration/tally_mcp',9000,selected[0]['name'],selected[0]['identity'],tool,args,shutil.which('node'))
            view=display(raw['result'],tool)
            result={'tool':tool,'transport':'passed','display':'passed','rows':view['total_rows'],
                    'financial_ui_comparison':'pending'}
        except Exception as exc:
            result={'tool':tool,'transport_or_display':'failed','error_type':type(exc).__name__}
        results.append(result)
        print(json.dumps(result),flush=True)
        target=ROOT/options.output;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps({'commit':PIN,'observed_at':datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(),
            'scope':'explicit_test_company_read_only','results':results,'writes_attempted':0},indent=2))

if __name__=='__main__':main()
