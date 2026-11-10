"""One HTTP attempt, atomic provider-wide admission, no prompts/keys in ledger."""
import atexit,contextlib,contextvars,hashlib,json,math,os,re,secrets,time,urllib.request,urllib.error
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from functools import lru_cache
from sqlalchemy import create_engine,select,text
from sqlalchemy.orm import Session
from app.models.groq_quota import GroqQuotaRequest as Request,GroqQuotaCooldown as Cooldown

call_context=contextvars.ContextVar('groq_call_context',default={})
@contextlib.contextmanager
def context(**values):
    token=call_context.set(values)
    try:yield
    finally:call_context.reset(token)

def now():return datetime.now(timezone.utc)
def enabled():return os.getenv('PHILIXA_GROQ_QUOTA_ENABLED','0')=='1'
def duration(value):
    if not value:return None
    try:
        result=float(value)
    except (ValueError,TypeError):
        parts=re.findall(r'(\d+(?:\.\d+)?)(ms|s|m|h|d)',str(value))
        if ''.join(n+u for n,u in parts)!=str(value):return None
        result=sum(float(n)*{'ms':.001,'s':1,'m':60,'h':3600,'d':86400}[u] for n,u in parts)
    return result if math.isfinite(result) and 0<=result<=604800 else None

@dataclass
class GatewayResult:
    data:dict
    usage:dict
    quota_headers:dict
    request_id:str

class QuotaDeferred(Exception):
    def __init__(self,reason,retry_at=None,*,sent=False,status=None):
        self.reason=reason;self.retry_at=retry_at;self.sent=sent;self.status=status
        super().__init__(reason)

@lru_cache(maxsize=1)
def engine():
    from app.core.config import get_settings
    url=get_settings().database_url.replace('postgresql+asyncpg://','postgresql+psycopg://')
    if url.startswith('postgresql://'):url=url.replace('postgresql://','postgresql+psycopg://',1)
    result=create_engine(url,pool_size=3,max_overflow=2,pool_pre_ping=True,connect_args={'connect_timeout':5})
    atexit.register(result.dispose)
    return result

def estimate(payload):
    import tiktoken
    model=payload.get('model','')
    if model.startswith('openai/gpt-oss-'):encoding=tiktoken.get_encoding('o200k_harmony')
    else:
        # Conservative fallback for other already-configured Groq text models.
        messages=payload.get('messages',[])
        images=any(isinstance(m.get('content'),list) and any(p.get('type')=='image_url' for p in m['content']) for m in messages)
        if images:
            # Image encoding is not base64 length. Reserve a whole minute's
            # local allowance; actual provider usage calibrates the ledger.
            return int(int(os.getenv('PHILIXA_GROQ_TPM','8000'))*.9)
        size=len(json.dumps(messages,ensure_ascii=False).encode())
        return size+256+int(payload.get('max_completion_tokens',payload.get('max_tokens',2048)))
    raw=json.dumps({k:payload[k] for k in ('messages','tools','response_format') if k in payload},ensure_ascii=False,separators=(',',':'))
    count=len(encoding.encode(raw,disallowed_special=()))
    return math.ceil(count*1.1)+256+int(payload.get('max_completion_tokens',payload.get('max_tokens',2048)))

def bucket_for(key,model):
    # Scope may be configured identically for different keys in one provider org.
    scope=os.getenv('PHILIXA_GROQ_ACCOUNT_SCOPE') or hashlib.sha256(key.encode()).hexdigest()
    return hashlib.sha256((scope+':'+model).encode()).hexdigest()

def limits(state):
    result={k:int(os.getenv('PHILIXA_GROQ_'+k.upper(),str(v))) for k,v in {'rpm':30,'tpm':8000,'rpd':1000,'tpd':200000}.items()}
    for key,value in state.get('limits',{}).items():
        if key in result and isinstance(value,int) and value>0:result[key]=min(result[key],value)
    return result

def admit(bucket,tokens):
    stamp=now()
    with Session(engine()) as db,db.begin():
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(bucket[:15],16)})
        cool=db.get(Cooldown,bucket);state=cool.state if cool else {}
        lim=limits(state)
        if tokens>int(lim['tpm']*.9):raise QuotaDeferred('request_too_large')
        if state.get('until') and datetime.fromisoformat(state['until'])>stamp:
            raise QuotaDeferred(state.get('reason','minute_quota'),datetime.fromisoformat(state['until']))
        observed_tokens = False
        for metric,reason in (('tokens','minute_quota'),('requests','daily_quota')):
            reset=state.get(metric+'_reset')
            remaining=state.get('remaining_'+metric)
            fresh = reset and datetime.fromisoformat(reset)>stamp and remaining is not None
            if metric=='tokens':observed_tokens = bool(fresh)
            # Keep 10% headroom, but do not also impose an incompatible rolling
            # token window on a current provider remaining-capacity snapshot.
            required=tokens+math.ceil(lim['tpm']*.1) if metric=='tokens' else 1
            if fresh and remaining<required:
                raise QuotaDeferred(reason,datetime.fromisoformat(reset))
        rows=list(db.scalars(select(Request).where(Request.bucket==bucket,Request.created_at>stamp-timedelta(days=1))))
        minute=[r for r in rows if r.created_at>stamp-timedelta(seconds=60)]
        if len(rows)>=lim['rpd'] or sum(r.charged_tokens for r in rows)+tokens>lim['tpd']:
            raise QuotaDeferred('daily_quota',min(r.created_at for r in rows)+timedelta(days=1) if rows else None)
        if len(minute)>=max(1,int(lim['rpm']*.9)) or (not observed_tokens and sum(r.charged_tokens for r in minute)+tokens>int(lim['tpm']*.9)):
            raise QuotaDeferred('minute_quota',min(r.created_at for r in minute)+timedelta(seconds=61))
        ident=secrets.token_hex(16);ctx=call_context.get()
        db.add(Request(id=ident,bucket=bucket,task_id=ctx.get('task_id'),revision=ctx.get('revision'),status='reserved',
            reserved_tokens=tokens,charged_tokens=tokens,metadata_json={},created_at=stamp,updated_at=stamp))
        if cool:
            state=dict(state)
            for metric,amount in (('tokens',tokens),('requests',1)):
                if state.get(metric+'_reset') and datetime.fromisoformat(state[metric+'_reset'])>stamp and state.get('remaining_'+metric) is not None:
                    state['remaining_'+metric]=max(0,state['remaining_'+metric]-amount)
            cool.state=state
        return ident

def free_call_limit():
    """Optional local cap, distinct from provider-account daily admission."""
    configured=os.getenv('PHILIXA_GROQ_LOCAL_DAILY_CALLS')
    if configured is not None:
        value=int(configured)
        if value<=0:raise ValueError('Local daily calls must be positive')
        return value
    return None if enabled() else 50


def safe_headers(headers):
    allow=('retry-after','x-ratelimit-limit-requests','x-ratelimit-limit-tokens','x-ratelimit-remaining-requests',
        'x-ratelimit-remaining-tokens','x-ratelimit-reset-requests','x-ratelimit-reset-tokens')
    return {k:str(headers.get(k))[:64] for k in allow if headers.get(k) is not None}

def settle(ident,bucket,usage,headers,status,latency,reason=None,retry_at=None):
    with Session(engine()) as db,db.begin():
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(bucket[:15],16)})
        row=db.get(Request,ident);row.status='succeeded' if status==200 else 'uncertain' if status is None else 'rejected'
        rejected_before_generation=status in (400,401,403,404,405,413,415,422) and not usage
        if rejected_before_generation:row.charged_tokens=0
        cached=int((usage.get('prompt_tokens_details') or {}).get('cached_tokens',0))
        if usage.get('total_tokens') is not None:row.charged_tokens=max(0,int(usage['total_tokens'])-cached)
        row.metadata_json={'usage':usage,'headers':headers,'http_status':status,'latency_ms':round(latency*1000)};row.updated_at=now()
        cool=db.get(Cooldown,bucket)
        if not cool:cool=Cooldown(bucket=bucket,state={},updated_at=now());db.add(cool)
        state=dict(cool.state);observed=dict(state.get('limits',{}))
        if rejected_before_generation and 'x-ratelimit-remaining-tokens' not in headers and state.get('remaining_tokens') is not None:
            # Release this admission's token reservation, not its transmitted request.
            state['remaining_tokens']=min(limits(state)['tpm'],state['remaining_tokens']+row.reserved_tokens)
        for h,k in (('x-ratelimit-limit-requests','rpd'),('x-ratelimit-limit-tokens','tpm')):
            try:
                value=int(headers.get(h,''))
                if value>0:observed[k]=min(observed.get(k,value),value)
            except ValueError:pass
        state['limits']=observed
        for metric in ('tokens','requests'):
            delay=duration(headers.get('x-ratelimit-reset-'+metric))
            try:remaining=int(headers.get('x-ratelimit-remaining-'+metric,''))
            except ValueError:continue
            if remaining>=0 and delay is not None:
                inflight=list(db.scalars(select(Request).where(Request.bucket==bucket,Request.id!=ident,
                    Request.status=='reserved',Request.created_at>now()-timedelta(seconds=60))))
                deduction=sum(r.charged_tokens if metric=='tokens' else 1 for r in inflight)
                state['remaining_'+metric]=max(0,remaining-deduction)
                state[metric+'_reset']=(now()+timedelta(seconds=delay)).isoformat()
        if reason and retry_at:
            until=datetime.fromisoformat(state['until']) if state.get('until') else now()
            if retry_at>until:state.update(until=retry_at.isoformat(),reason=reason)
        cool.state=state;cool.updated_at=now()

def request(url,payload,headers,timeout_seconds):
    payload=dict(payload)
    if payload.get('max_completion_tokens') is None and payload.get('max_tokens') is None:
        payload['max_completion_tokens']=2048
    key=headers.get('Authorization','').removeprefix('Bearer ')
    bucket=bucket_for(key,payload.get('model','unknown'))
    try:ident=admit(bucket,estimate(payload))
    except QuotaDeferred:raise
    except Exception:raise QuotaDeferred('quota_ledger_unavailable') from None
    started=time.monotonic()
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),method='POST',headers={
        'Content-Type':'application/json','User-Agent':'Mozilla/5.0 (compatible; PhilixaAI/6.0; +https://philixa.ai)',**headers})
    try:
        with urllib.request.urlopen(req,timeout=timeout_seconds) as response:
            data=json.loads(response.read().decode());h=safe_headers(response.headers)
        usage=data.get('usage',{})
        settle(ident,bucket,usage,h,200,time.monotonic()-started)
        return GatewayResult(data,usage,h,ident)
    except urllib.error.HTTPError as exc:
        # Parse bounded complete error JSON before selecting safe diagnostic fields.
        # Cutting it at 2000 chars hid codes whenever failed_generation was long.
        h=safe_headers(exc.headers);body=exc.read(128*1024).decode(errors='replace')
        if exc.code==429 or exc.code in (500,502,503,504):
            daily=bool(re.search(r'\b(TPD|RPD)\b|tokens per day|requests per day',body,re.I))
            reason='daily_quota' if daily else 'minute_quota' if exc.code==429 else 'provider_unavailable'
            delay=duration(h.get('retry-after'))
            if delay is None:delay=duration(h.get('x-ratelimit-reset-requests' if daily else 'x-ratelimit-reset-tokens'))
            retry=now()+timedelta(seconds=delay if delay is not None else 86400 if daily else 65)
            settle(ident,bucket,{},h,exc.code,time.monotonic()-started,reason,retry)
            raise QuotaDeferred(reason,retry,sent=True,status=exc.code) from None
        settle(ident,bucket,{},h,exc.code,time.monotonic()-started)
        from app.ai.provider import AIExtractionError
        failure=AIExtractionError('Groq request rejected: HTTP '+str(exc.code))
        failure.status_code=exc.code
        # Expose an allowlisted code, never provider messages/failed generations
        # (which can contain prompts, documents or other sensitive content).
        try:error_data=json.loads(body).get('error',{});provider_code=error_data.get('code') or error_data.get('type')
        except (ValueError,AttributeError):error_data={};provider_code=None
        failure.provider_code=provider_code if provider_code in (
            'json_validate_failed','invalid_request_error','model_not_found',
            'context_length_exceeded','rate_limit_exceeded') else None
        if provider_code=='json_validate_failed':
            generated=error_data.get('failed_generation')
            summary={'json_valid':False,'generated_type':type(generated).__name__}
            if isinstance(generated,str):
                stripped=generated.strip()
                summary.update(character_count=len(generated),
                    starts_as='object' if stripped.startswith('{') else 'array' if stripped.startswith('[') else 'fence' if stripped.startswith('```') else 'empty' if not stripped else 'text',
                    ends_as='object' if stripped.endswith('}') else 'array' if stripped.endswith(']') else 'other')
            try:
                decoded=json.loads(generated)
                summary={'json_valid':True,'root_type':type(decoded).__name__}
                if isinstance(decoded,dict):
                    expected=payload.get('response_format',{}).get('json_schema',{}).get('schema',{})
                    summary['missing_required_count']=len(set(expected.get('required',[]))-set(decoded))
                    summary['unexpected_field_count']=len(set(decoded)-set(expected.get('properties',{})))
                    if expected:
                        from jsonschema import Draft202012Validator
                        errors=list(Draft202012Validator(expected).iter_errors(decoded))
                        fields=set(expected.get('properties',{}))
                        summary['schema_error_count']=len(errors)
                        summary['schema_errors']=[{'path':[p if isinstance(p,int) or p in fields else '<field>' for p in error.path],
                                                   'validator':error.validator} for error in errors[:12]]
            except json.JSONDecodeError as error:
                summary.update(json_error=error.msg,error_line=error.lineno,error_column=error.colno)
            except TypeError:pass
            # Structural diagnostics only: no generated text, values or arbitrary keys.
            failure.output_structure=summary
            if isinstance(generated,str) and re.fullmatch(r"I[’']m sorry, but I can[’']t help with that\.?",generated.strip(),re.I):
                failure.provider_code='model_refusal'
        raise failure from exc
    except QuotaDeferred:raise
    except Exception:
        try:settle(ident,bucket,{}, {},None,time.monotonic()-started)
        except Exception:pass # Reservation survives an unavailable ledger; no resend.
        raise QuotaDeferred('provider_uncertain',sent=True) from None
