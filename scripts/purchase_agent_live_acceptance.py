"""Review-only synthetic purchase on the existing Philixa Test scope. No posting."""
import asyncio,json,uuid
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import select
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyReadCompany
from app.models.organization_membership import OrganizationMembership
from app.services import purchase_draft_service as drafts,purchase_message,purchase_agent as agent,purchase_native_context as native
from app.services.purchase_conversation import Reply

OUTPUT=Path('/app/data/purchase-agent-live-acceptance.json')

async def main():
    async with AsyncSessionLocal() as db:
        company=await db.get(TallyReadCompany,'34daa9ea76cef23a9b8c984d6eec8992')
        if not company or company.name!='Philixa Test' or not company.enabled:raise RuntimeError('Approved Philixa Test unavailable')
        member=await db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id==company.organization_id,
            OrganizationMembership.status=='active',OrganizationMembership.role=='owner'))
        if not member:raise RuntimeError('Active test workspace owner unavailable')
        p=SimpleNamespace(organization_id=company.organization_id,user_id=member.user_id,role=member.role,session_id='purchase-agent-local-acceptance')
        report=json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
        if not report.get('draft_id'):
            text='Sharma Traders se 50 Cement bags liye'
            mentions=await purchase_message.extract(text)
            content=agent.apply_updates({'lines':[{}]},mentions)
            assert content['party_name']=='Sharma Traders' and content['lines'][0]['item_name']=='Cement'
            assert content['entry_date'] is None and content['lines'][0]['rate'] is None
            result=await drafts.create_draft(db,p,drafts.DraftCreate(company_id=company.id,content=content))
            report={'draft_id':result['id'],'live_understanding':True,'missing_date_not_invented':True,'posting':False}
            OUTPUT.write_text(json.dumps(report,indent=2))
        result=await agent.state(db,p,report['draft_id'])
        context=result.get('purchase_context',{})
        if context.get('cache_id') and context.get('status')!='ready':
            row=await drafts.scoped_draft(db,p,report['draft_id'])
            context=await native.context(db,p,row,force=True)
            await native.refresh_purchase_history({},context['cache_id'])
            result=await agent.state(db,p,report['draft_id']);context=result['purchase_context']
        report.update(native_context_status=context.get('status'),context_reason=context.get('reason'),
            rate_suggestions=result.get('suggestions',[]),grouped_response=result['response'])
        if context.get('status')=='ready':
            suggestion=next((s for s in result['suggestions'] if s['field']=='0:rate'),None)
            assert suggestion and suggestion['value']=='350.00',result['suggestions']
            req=Reply(expected_revision=result['proposal']['revision'],request_id=uuid.uuid4().hex,message='Rate 351 tha, bill AGENT-LOCAL-REVIEW-01')
            corrected=await agent.answer(db,p,report['draft_id'],req)
            repeated=await agent.answer(db,p,report['draft_id'],req)
            assert corrected['proposal']['revision']==repeated['proposal']['revision']
            assert corrected['proposal']['content']['lines'][0]['rate']=='351'
            assert corrected['proposal']['content']['invoice_number']=='AGENT-LOCAL-REVIEW-01'
            report.update(explicit_rate_preserved=True,multiple_fields_understood=True,request_deduplicated=True,
                revision=corrected['proposal']['revision'])
            async with AsyncSessionLocal() as fresh:
                reloaded=await agent.state(fresh,p,report['draft_id'])
                assert reloaded['proposal']['revision']==report['revision']
                report['database_reload_preserved']=True
        OUTPUT.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))

if __name__=='__main__':asyncio.run(main())
