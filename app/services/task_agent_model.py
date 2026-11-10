"""Schema constrained next-step proposal; no model-controlled execution."""
import asyncio
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.ai.provider import GroqProvider, _post_json, AIExtractionError
from app.core.config import get_settings
from app.services.task_agent_runtime import Decision
from app.services.task_agent_prompts import system_prompt,metadata


class WireDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['tool','needs_input','needs_approval','finish']
    tool: str | None
    arguments_json: str = Field(max_length=12000)
    summary: str = Field(max_length=1000, description='Internal next-step rationale; never shown directly to the user.')
    user_response: str = Field(default='', max_length=1000, description='Direct user-facing question or answer in the user language. No third-person planning or instructions to another assistant.')


class AgentProviderUnavailable(Exception):
    def __init__(self,status=None,diagnostic=None):
        self.status=status
        self.diagnostic=diagnostic
        self.code={401:'provider_authentication',403:'provider_access_denied',
            429:'provider_rate_limit',503:'provider_unavailable'}.get(status,'provider_request_failed')
        self.safe_message={403:'Groq access denied (403). Task saved; check provider/network access. No entry posted.',
            429:'Groq free-tier rate limit reached. Task saved; wait before resuming.'}.get(status,
            'Groq request unavailable. Task saved; no successful entry assumed.')
        super().__init__(self.code)


def planner_context(state,schemas):
    # Session identifiers, request hashes and execution bookkeeping are not
    # model context. Preserve domain evidence and every tool observation.
    fields=('messages','message_times','outcome','company_id','draft_id','draft_revision',
        'prefetched_draft','observations','issues','tool_groups','attachment_sources','attachment_document_ids')
    task={k:state[k] for k in fields if k in state}
    task['messages']=[{'message_index':i,'text':m} for i,m in enumerate(state.get('messages',[]))]
    task['messages']=[m for i,m in enumerate(task['messages']) if not any(n['text']==m['text'] for n in task['messages'][i+1:])]
    # Keep the most recent presentation for each draft plus non-draft evidence.
    observations=task.get('observations',[])
    task['observations']=[o for i,o in enumerate(observations) if not o.get('data',{}).get('proposal') or
        not any(n.get('data',{}).get('draft_id')==o.get('data',{}).get('draft_id') for n in observations[i+1:])]
    if any(o.get('data',{}).get('proposal',{}).get('revision')==state.get('draft_revision') for o in task['observations']):
        task.pop('prefetched_draft',None)
    if state.get('attachment_document_ids'):
        # Send a source index, not duplicate full OCR/draft snapshots. Typed tools
        # read the exact requested fields with fresh permission/revision checks.
        indexed=[]
        for source in state.get('attachment_sources',[])[:10]:
            indexed.append({k:source.get(k) for k in ('document_id','filename','status','extraction_status','extraction_generation','boundary_issue')})
            indexed[-1]['drafts']=[{'id':draft['id'],'revision':draft['revision'],
                'invoice_number':draft.get('content',{}).get('invoice_number'),
                'available_fields':[key for key,value in draft.get('content',{}).items() if value is not None]}
                for draft in source.get('drafts',[])[:10]]
        task['attachment_sources']=indexed
        task['attachment_coverage']={'documents_shown':len(indexed),'total':len(state.get('attachment_document_ids',[])),
            'instruction':'Ask for a narrower bill selection if the source is not shown; never assume complete coverage.'}
        task.pop('prefetched_draft',None)
        task['observations']=[o for o in task.get('observations',[]) if not o.get('data',{}).get('attachment_sources') and not o.get('data',{}).get('proposal')]
    task['executions']=[{k:e[k] for k in ('tool','status') if k in e}
        for e in state.get('executions',[])]
    def compact(value):
        if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if v is not None}
        if isinstance(value,list):return [compact(v) for v in value]
        return value
    def schema_min(value):
        if isinstance(value,dict):return {k:schema_min(v) for k,v in value.items() if k!='title'}
        if isinstance(value,list):return [schema_min(v) for v in value]
        return value
    return json.dumps({'tools':schema_min(schemas),'task':compact(task)},ensure_ascii=False,separators=(',',':'))


def request_payload(state,schemas,*,prompt_version=None):
    schema = WireDecision.model_json_schema()
    schema['required'] = list(schema['properties'])
    context = planner_context(state,schemas)
    if len(context) > 100000:
        raise ValueError('Task evidence exceeds model budget; narrow the context read.')
    return dict(model='openai/gpt-oss-20b', temperature=0, reasoning_effort='low', max_completion_tokens=2048,
        messages=[dict(role='system', content=system_prompt(state,schemas,prompt_version)+'\nResponse contract: summary is internal rationale only. user_response is the concise direct question/answer for the user, in their language; never instructions to another assistant. Interpret the latest message first: general capability/help questions do not refer to attached bills merely because attachments exist.'),
            dict(role='user', content=context)],
        response_format={'type':'json_schema','json_schema':{'name':'agent_decision','strict':True,'schema':schema}})

async def choose(state, schemas, *, prompt_version=None):
    settings = get_settings()
    provider = GroqProvider(settings)
    key = settings.ai_api_key or settings.groq_api_key
    if not key:raise ValueError('Configured Groq key unavailable')
    if settings.ai_economy_model.replace('groq/','')!='openai/gpt-oss-20b':
        raise ValueError('Task agent baseline requires configured GPT-OSS 20B')
    payload=request_payload(state,schemas,prompt_version=prompt_version)
    try:
        data = await asyncio.wait_for(asyncio.to_thread(_post_json, provider.base_url, payload,
            {'Authorization': 'Bearer '+key}, timeout_seconds=25, max_attempts=1), timeout=30)
    except AIExtractionError as exc:
        known=('json_validate_failed','failed_generation','context_length_exceeded','max_completion_tokens','invalid_request_error','model_not_found')
        diagnostic=next((marker for marker in known if marker in str(exc)),None)
        raise AgentProviderUnavailable(getattr(exc.__cause__,'code',None),diagnostic) from None
    message = data['choices'][0]['message']
    if message.get('refusal'):
        raise ValueError('Model refused task')
    wire = WireDecision.model_validate_json(message['content'])
    # No arguments are executed for a question/finish. Models may legitimately
    # emit an empty string there despite the outer strict string schema.
    arguments=json.loads(wire.arguments_json) if wire.kind=='tool' else {}
    result = Decision.model_validate(dict(kind=wire.kind, tool=wire.tool,
        arguments=arguments, summary=wire.summary, user_response=wire.user_response))
    return result, {**data.get('usage', {}),'prompt_package':metadata(state,schemas,prompt_version)}
