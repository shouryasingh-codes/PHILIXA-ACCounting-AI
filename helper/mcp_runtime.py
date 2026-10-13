"""Private stdio child and a company-bound read gateway, never a public MCP server."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import threading
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyError
from app.services.tally_mcp import PIN, validate_arguments

MAX_BYTES = 1_500_000

def scope_envelope(xml, company):
    if len(xml)>MAX_BYTES or b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
        raise TallyError('Unsafe MCP envelope.')
    try: root = ET.fromstring(xml)
    except ET.ParseError: raise TallyError('Invalid MCP envelope.') from None
    header = root.find('HEADER')
    kind=(header.findtext('TALLYREQUEST') or '').casefold() if header is not None else ''
    if root.tag != 'ENVELOPE' or header is None or kind not in ('export','export data'):
        raise TallyError('Direct MCP mutation rejected.')
    if any(e.tag.upper() in ('IMPORTDATA','TALLYMESSAGE','FUNCTION','ACTION') for e in root.iter()):
        raise TallyError('MCP mutation envelope rejected.')
    body = root.find('BODY')
    if body is None: raise TallyError('Invalid MCP body.')
    if kind=='export data':
        export=body.find('EXPORTDATA')
        desc=export.find('REQUESTDESC') if export is not None else None
        if desc is None:raise TallyError('Invalid MCP report body.')
    else:
        desc = body.find('DESC')
        if desc is None: desc = ET.SubElement(body, 'DESC')
    variables = desc.find('STATICVARIABLES')
    if variables is None: variables = ET.SubElement(desc, 'STATICVARIABLES')
    # Remove every competing company variable, including malicious duplicate nesting.
    for parent in root.iter():
        for child in list(parent):
            if child.tag.upper() == 'SVCURRENTCOMPANY': parent.remove(child)
    ET.SubElement(variables, 'SVCURRENTCOMPANY').text = company
    return ET.tostring(root, encoding='utf-8')

class ReadGateway:
    def __init__(self, company, port):
        if not isinstance(company,str) or not company or len(company)>200 or type(port)!=int or not 1<=port<=65535:
            raise TallyError('Invalid fixed Tally gateway.')
        self.token = secrets.token_urlsafe(32)
        token = self.token
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(handler):
                try:
                    if handler.path != '/'+token: raise TallyError('Gateway authorization invalid.')
                    length = int(handler.headers.get('Content-Length','0'))
                    if not 0<length<=MAX_BYTES: raise TallyError('Gateway request too large.')
                    xml = scope_envelope(handler.rfile.read(length), company)
                    request = Request(f'http://127.0.0.1:{port}', data=xml, headers={'Content-Type':'text/xml'}, method='POST')
                    with urlopen(request, timeout=10) as response:
                        output=response.read(MAX_BYTES+1)
                    if len(output)>MAX_BYTES: raise TallyError('MCP report too large.')
                    # HTTP 200 can contain a rejected canned report. Do not pass it
                    # to upstream cleanup as an apparently successful empty report.
                    normalized=output.lower()
                    if any(marker in normalized for marker in (b'<lineerror>',b'<error>',b'<tallyrequesterror>',b'unknown request',b'error in tdl')):
                        raise TallyError('Tally rejected the report.')
                    handler.send_response(200); handler.send_header('Content-Type','text/xml'); handler.end_headers()
                    handler.wfile.write(output)
                except Exception:
                    handler.send_response(502); handler.end_headers()
                    handler.wfile.write(b'gateway_read_failed')
        self.server = HTTPServer(('127.0.0.1',0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}/{token}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    def __enter__(self): self.thread.start(); return self
    def __exit__(self,*args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

class StdioClient:
    def __init__(self, bundle, gateway_url, node=None):
        self.bundle = Path(bundle).resolve()
        manifest = json.loads((self.bundle/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('commit')!=PIN: raise TallyError('MCP bundle pin mismatch.')
        for relative, expected in manifest['runtimeFiles'].items():
            path=(self.bundle/relative).resolve()
            if not path.is_relative_to(self.bundle.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
                raise TallyError('MCP bundle integrity check failed.')
        executable = str(node or self.bundle/'node.exe')
        # Child inherits no accounting credentials / provider secrets.
        env={k:os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP') if k in os.environ}
        env.update(TALLY_URL=gateway_url, TALLY_MCP_PERMISSION='read')
        self.process=subprocess.Popen([executable,str(self.bundle/'dist'/'philixa.js')], cwd=self.bundle,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.outputs=queue.Queue(); self.counter=0
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        try:
            self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'philixa-connector','version':'0.1.0'}})
            self.notify('notifications/initialized')
        except Exception:
            self.close();raise
    def _read(self):
        try:
            while True:
                line=self.process.stdout.readline(MAX_BYTES+1)
                if not line: break
                if len(line)>MAX_BYTES: self.outputs.put(None);return
                self.outputs.put(json.loads(line))
        except Exception: pass
        self.outputs.put(None)
    def notify(self, method):
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','method':method})+'\n'); self.process.stdin.flush()
    def request(self, method, params, timeout=18):
        self.counter+=1; ident=self.counter
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params},allow_nan=False)+'\n')
        self.process.stdin.flush()
        try: response=self.outputs.get(timeout=timeout)
        except queue.Empty:
            self.close(); raise TallyError('MCP child timeout; read not verified.') from None
        if not response or response.get('id')!=ident or 'error' in response:
            raise TallyError('MCP child protocol failed.')
        return response['result']
    def call(self, tool, arguments):
        validate_arguments(tool, arguments)
        result=self.request('tools/call',{'name':tool,'arguments':arguments})
        if result.get('isError'): raise TallyError('MCP read failed.')
        return result
    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        for stream in (self.process.stdin,self.process.stdout):
            if stream:stream.close()
        self.reader.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

def execute_read(bundle, port, company, identity, tool, arguments, node=None):
    """One isolated process/cache per request; no global company/session mutation."""
    import asyncio
    from app.services.tally_connector import local_operation
    validate_arguments(tool,arguments)
    discovered=asyncio.run(local_operation('discover',port=port))
    if sum(c['identity']==identity and c['name']==company for c in discovered['companies'])!=1 or sum(c['name']==company for c in discovered['companies'])!=1:
        raise TallyError('Approved company identity changed/unavailable.')
    with ReadGateway(company,port) as gateway, StdioClient(bundle,gateway.url,node) as client:
        result=client.call(tool,arguments)
    return {'backend':'mcp','commit':PIN,'tool':tool,'company':company,'identity':identity,'result':result}

def execute_compile(bundle, port, company, identity, tool, arguments, node=None):
    """Compile a durable draft. Gateway stays export-only: compilation cannot post."""
    import asyncio
    from app.services.tally_connector import local_operation
    from app.services.tally_mcp_write_validation import validate_write
    contract=validate_write(tool,arguments)
    if contract['category']!='write' or not contract['builderAvailable']:raise TallyError('Not a write compiler.')
    discovered=asyncio.run(local_operation('discover',port=port))
    if sum(c['identity']==identity and c['name']==company for c in discovered['companies'])!=1 or sum(c['name']==company for c in discovered['companies'])!=1:
        raise TallyError('Approved company identity changed/unavailable.')
    with ReadGateway(company,port) as gateway,StdioClient(bundle,gateway.url,node) as client:
        result=client.request('tools/call',{'name':'philixa_compile','arguments':{'tool':tool,'arguments':arguments}})
    if result.get('isError'):raise TallyError('MCP draft compiler failed.')
    try:xml=json.loads(result['content'][0]['text'])['xml'];root=ET.fromstring(xml)
    except (ValueError,KeyError,IndexError,TypeError,ET.ParseError):raise TallyError('Invalid compiler response.') from None
    if len(xml)>MAX_BYTES or root.findtext('./HEADER/TALLYREQUEST')!='Import Data':raise TallyError('Invalid compiler envelope.')
    request=root.find('./BODY/IMPORTDATA/REQUESTDESC')
    if request is None:raise TallyError('Invalid compiler scope.')
    variables=request.find('STATICVARIABLES')
    if variables is None:variables=ET.SubElement(request,'STATICVARIABLES')
    for parent in root.iter():
        for child in list(parent):
            if child.tag=='SVCURRENTCOMPANY':parent.remove(child)
    ET.SubElement(variables,'SVCURRENTCOMPANY').text=company
    xml=ET.tostring(root,encoding='unicode')
    return {'backend':'mcp','commit':PIN,'tool':tool,'company':company,'identity':identity,
            'xml':xml,'xml_sha256':hashlib.sha256(xml.encode()).hexdigest(),'posting_enabled':False}
