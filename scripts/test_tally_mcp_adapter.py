import json
from pathlib import Path
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from xml.etree import ElementTree as ET
import pytest
from jsonschema import Draft202012Validator
from app.services.tally_connector import TallyError
from app.services.tally_mcp import CONTRACTS, PIN, validate_arguments
from helper.mcp_runtime import ReadGateway, StdioClient, scope_envelope

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=ROOT/'integration'/'tally_mcp'
EXPORT=b'<ENVELOPE><HEADER><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Ledgers</ID></HEADER><BODY><DESC><STATICVARIABLES><SVCURRENTCOMPANY>Wrong</SVCURRENTCOMPANY></STATICVARIABLES></DESC></BODY></ENVELOPE>'

@pytest.mark.parametrize('contract',list(CONTRACTS.values()),ids=list(CONTRACTS))
def test_complete_contract(contract):
    Draft202012Validator.check_schema(contract['inputSchema'])
    assert contract['permission'] and contract['verification'] and contract['preview']
    assert contract['state'] in ('read_candidate','prerequisite_blocked')
    if contract['category']!='read':assert contract['blockedReason']

@pytest.mark.parametrize('name',[n for n,c in CONTRACTS.items() if c['category']!='read'])
def test_non_read_never_dispatches(name):
    with pytest.raises(TallyError):validate_arguments(name,{})

def test_scope_replaces_duplicate_companies_and_escapes_name():
    xml=EXPORT.replace(b'</DESC>',b'<SVCURRENTCOMPANY>Evil</SVCURRENTCOMPANY></DESC>')
    root=ET.fromstring(scope_envelope(xml,'A & B'))
    assert [v.text for v in root.iter('SVCURRENTCOMPANY')]==['A & B']

def test_native_report_scope():
    xml=b'<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER><BODY><EXPORTDATA><REQUESTDESC><REPORTNAME>Trial Balance</REPORTNAME></REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>'
    root=ET.fromstring(scope_envelope(xml,'Approved'))
    assert root.findtext('BODY/EXPORTDATA/REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY')=='Approved'

@pytest.mark.parametrize('xml',[
    b'<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER></ENVELOPE>',
    EXPORT.replace(b'<DESC>',b'<DESC><ACTION>Create</ACTION>'),
    b'<!DOCTYPE a [<!ENTITY x "evil">]>'+EXPORT,
    b'<invalid>',
])
def test_gateway_rejects_mutations(xml):
    with pytest.raises(TallyError):scope_envelope(xml,'Approved')

@pytest.mark.parametrize('tool,args',[
    ('get_ledgers',{'url':'http://evil'}),('get_ledgers',{'query':'x" OR 1=1'}),
    ('get_ledgers',{'query':'x\\y'}),('get_vouchers',{'limit':9007199254740992}),
    ('invented',{}),('query_sql',{'sql':'SELECT * FROM organizations'}),
])
def test_strict_arguments(tool,args):
    with pytest.raises(TallyError):validate_arguments(tool,args)

@pytest.fixture
def child():
    if not shutil.which('node') or not (BUNDLE/'manifest.json').is_file():pytest.skip('Build adapter first')
    recorded=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            xml=self.rfile.read(int(self.headers['Content-Length']))
            recorded.append(xml)
            output=b'<ENVELOPE><BODY><DATA><ROW><NAME>Approved</NAME><CLOSINGBALANCE>5</CLOSINGBALANCE></ROW></DATA></BODY></ENVELOPE>'
            self.send_response(200);self.end_headers();self.wfile.write(output)
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with ReadGateway('Approved',server.server_port) as gateway, StdioClient(BUNDLE,gateway.url,shutil.which('node')) as client:
            yield client, recorded
    finally:server.shutdown();server.server_close();thread.join(timeout=2)

def test_actual_stdio_inventory_and_company_bound_read(child):
    client, recorded=child
    tools=client.request('tools/list',{})['tools']
    assert {t['name'] for t in tools}==set(CONTRACTS)
    assert all(t['inputSchema']==CONTRACTS[t['name']]['inputSchema'] for t in tools)
    result=client.call('get_ledgers',{})
    assert not result.get('isError') and recorded
    assert all([e.text for e in ET.fromstring(xml).iter('SVCURRENTCOMPANY')]==['Approved'] for xml in recorded)

@pytest.mark.parametrize('tool',['create_ledger','confirm_write','set_company','set_period','get_audit_log','query_sql'])
def test_child_itself_blocks_direct_dangerous_calls(child,tool):
    client, recorded=child
    result=client.request('tools/call',{'name':tool,'arguments':{}})
    assert result['isError'] and not recorded

def test_child_compiler_cannot_import(child):
    client, recorded=child
    result=client.request('tools/call',{'name':'philixa_compile','arguments':{
        'tool':'create_godown','arguments':{'name':'Test & Godown','parent':'Primary'}}})
    assert not result.get('isError') and not recorded
    xml=json.loads(result['content'][0]['text'])['xml']
    assert ET.fromstring(xml).find('.//GODOWN') is not None
    with pytest.raises(TallyError):scope_envelope(xml.encode(),'Approved')

def test_original_upstream_source_kept():
    import hashlib
    manifest=json.loads((BUNDLE/'manifest.json').read_text())
    assert manifest['commit']==PIN
    for relative,digest in manifest['originalFiles'].items():
        assert hashlib.sha256((ROOT/'third_party'/'tally_mcp'/relative).read_bytes()).hexdigest()==digest
