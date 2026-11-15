"""Provider selection and cancellable Gemini transport; no silent fallback."""
import asyncio, contextlib, contextvars, json, os, re, time
import httpx
from app.core.config import get_settings
from app.core.redis import get_redis_client
REDIS_KEY = 'philixa:active_ai_engine'
_selected = contextvars.ContextVar('philixa_selected_provider', default=None)
http_client = httpx.AsyncClient
_transports = {}  # One owned pool per running event loop, closed by its runtime.

class EngineRequestError(Exception):
    def __init__(self, code, status=None, diagnostic=None):
        self.code=code; self.status=status; self.diagnostic=diagnostic
        super().__init__(code)  # Never log a URL, key or response body.


class EngineTimeout(TimeoutError):
    def __init__(self, diagnostic):
        self.diagnostic=diagnostic
        super().__init__('Gemini request deadline exceeded')


async def start_transport():
    loop=asyncio.get_running_loop()
    if loop in _transports:
        _transports[loop]['owners']+=1
        return
    # TLS verification remains enabled; no credentials on the shared client.
    client=http_client(timeout=httpx.Timeout(20,connect=3,write=3,pool=1),
        limits=httpx.Limits(max_connections=10,max_keepalive_connections=5,keepalive_expiry=30),
        follow_redirects=False)
    _transports[loop]={'client':client,'owners':1}


async def close_transport():
    loop=asyncio.get_running_loop()
    entry=_transports.get(loop)
    if not entry:return
    entry['owners']-=1
    if entry['owners']==0:
        _transports.pop(loop,None)
        await entry['client'].aclose()


@contextlib.asynccontextmanager
async def transport_lifespan():
    await start_transport()
    try:yield
    finally:await close_transport()


@contextlib.asynccontextmanager
async def gemini_client():
    entry=_transports.get(asyncio.get_running_loop())
    if entry:
        yield entry['client']
    else:
        # One-off scripts/tests also close their resources; app/worker runtimes
        # use transport_lifespan/start_transport to reuse a live pool.
        async with http_client(follow_redirects=False) as client:yield client


class TransportTiming:
    """Record only whitelisted phase names and monotonic times, never info."""
    def __init__(self, model):
        self.started=time.monotonic()
        self.values={'model':model,'phase':'client_setup'}
        self.starts={}

    async def trace(self, event, info):
        parts=event.split('.')
        if len(parts)!=3:return
        _,operation,state=parts
        names={'connect_tcp':'tcp','start_tls':'tls','send_request_headers':'request_headers',
            'send_request_body':'request_body','receive_response_headers':'response_headers',
            'receive_response_body':'response_body'}
        if operation not in names or state not in ('started','complete','failed'):return
        phase=names[operation]
        if state=='started':
            self.values['phase']=phase
            self.starts[phase]=time.monotonic()
        elif state=='complete':
            if phase in self.starts:self.values[phase+'_ms']=round((time.monotonic()-self.starts[phase])*1000)
            if phase=='request_body':
                self.values['request_sent_ms']=round((time.monotonic()-self.started)*1000)
                self.values['phase']='response_headers'
            elif phase=='response_headers':self.values['headers_received_ms']=round((time.monotonic()-self.started)*1000)

    def snapshot(self):
        return {**self.values,'elapsed_ms':round((time.monotonic()-self.started)*1000)}

@contextlib.contextmanager
def provider_scope(engine):
    if engine not in ('groq','gemini'):raise ValueError('Unsupported AI provider')
    token=_selected.set(engine)
    try:yield
    finally:_selected.reset(token)

async def get_active_engine():
    if _selected.get():return _selected.get()
    if os.getenv('PYTEST_CURRENT_TEST'):return 'groq'
    try:
        async with asyncio.timeout(2):
            redis=await get_redis_client(); value=await redis.get(REDIS_KEY)
        if value:
            value=value.decode() if isinstance(value,bytes) else str(value)
            if value in ('groq','gemini'):return value
            raise EngineRequestError('provider_selection_invalid')
    except EngineRequestError:raise
    except Exception:raise EngineRequestError('provider_selection_unavailable') from None
    settings=get_settings()
    value=os.getenv('PHILIXA_ACTIVE_AI_ENGINE',settings.ai_economy_provider or 'groq').strip().lower()
    if value not in ('groq','gemini'):raise EngineRequestError('provider_selection_invalid')
    return value

async def set_active_engine(engine):
    if engine not in ('groq','gemini'):raise ValueError('Unsupported AI provider')
    try:
        async with asyncio.timeout(2):
            redis=await get_redis_client();await redis.set(REDIS_KEY,engine)
    except Exception:raise EngineRequestError('provider_selection_unavailable') from None
    return engine

def gemini_wire_schema(schema):
    """Small generation grammar; Pydantic remains the authoritative validator.

    Bounded arrays/strings are enforced after generation, not expanded into
    Gemini's grammar compiler. Resolve local refs; preserve all property types,
    enums, null alternatives and closed-object shape. No runtime validation or
    accounting/authority constraint is removed.
    """
    definitions=schema.get('$defs',{})
    omitted={'$defs','title','default','maxItems','minItems','maxLength','minLength','pattern'}
    def visit(node,trail=()):
        if isinstance(node,list):return [visit(v,trail) for v in node]
        if not isinstance(node,dict):return node
        if '$ref' in node:
            ref=node['$ref']
            if not ref.startswith('#/$defs/') or ref in trail or ref[8:] not in definitions:
                raise EngineRequestError('provider_schema_unsupported')
            return visit({**definitions[ref[8:]],**{k:v for k,v in node.items() if k!='$ref'}},(*trail,ref))
        result={k:visit(v,trail) for k,v in node.items() if k not in omitted}
        if node.get('type')=='object' and node.get('properties'):
            result['required']=list(node['properties'])
        return result
    return visit(schema)

async def call_gemini_json(system_prompt,user_content,schema=None,timeout_seconds=8):
    """One attempt within a total deadline. Caller owns any durable retry."""
    settings=get_settings();key=settings.gemini_api_key
    if not key:raise EngineRequestError('provider_authentication_missing')
    model=os.getenv('PHILIXA_GEMINI_MODEL','gemini-3.5-flash-lite').removeprefix('models/').strip()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',model):raise EngineRequestError('provider_model_invalid')
    config={'temperature':0,'maxOutputTokens':2048,'responseMimeType':'application/json'}
    if schema is not None:config['responseJsonSchema']=gemini_wire_schema(schema)
    payload={'systemInstruction':{'parts':[{'text':system_prompt}]},'contents':[{'role':'user','parts':[{'text':user_content}]}],'generationConfig':config}
    timing=TransportTiming(model)
    try:
        async with asyncio.timeout(timeout_seconds):
            async with gemini_client() as client:
                timing.values['phase']='connection_pool'
                response=await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                    headers={'x-goog-api-key':key},json=payload,
                    timeout=httpx.Timeout(timeout_seconds,connect=min(3,timeout_seconds),write=min(3,timeout_seconds),pool=min(1,timeout_seconds)),
                    extensions={'trace':timing.trace})
                timing.values.update(http_status=response.status_code,phase='decode')
                if response.status_code!=200:raise EngineRequestError('provider_http_error',response.status_code)
                data=response.json()
    except (httpx.TimeoutException,TimeoutError):raise EngineTimeout(timing.snapshot()) from None
    except httpx.RequestError:raise EngineRequestError('provider_transport_unavailable',diagnostic=timing.snapshot()) from None
    except EngineRequestError as exc:
        exc.diagnostic=timing.snapshot();raise
    except (ValueError,TypeError):raise EngineRequestError('provider_output_invalid',diagnostic=timing.snapshot()) from None
    candidates=data.get('candidates') or []
    if len(candidates)!=1 or candidates[0].get('finishReason')!='STOP':raise EngineRequestError('provider_output_incomplete')
    parts=candidates[0].get('content',{}).get('parts',[])
    output=''.join(p.get('text','') for p in parts if not p.get('thought'))
    try:json.loads(output)
    except (ValueError,TypeError):raise EngineRequestError('provider_output_invalid') from None
    usage=data.get('usageMetadata') or {}
    return output,{'provider':'gemini','model':model,'prompt_tokens':usage.get('promptTokenCount',0),
        'completion_tokens':usage.get('candidatesTokenCount',0),'thinking_tokens':usage.get('thoughtsTokenCount',0),
        'cached_tokens':usage.get('cachedContentTokenCount',0),'total_tokens':usage.get('totalTokenCount',0),
        'latency_ms':timing.snapshot()['elapsed_ms'],'transport':timing.snapshot(),'attempts':1}
