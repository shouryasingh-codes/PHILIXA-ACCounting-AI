"""Read-only evidence for the two authorised synthetic browser fixtures."""
import asyncio,json
from pathlib import Path
from sqlalchemy import select,func
from app.database.session import AsyncSessionLocal
from app.models.chat_attachment import ChatBillMessage,ChatBillAttachment
from app.models.bill_document import BillDocument
from app.models.purchase_draft import PurchaseDraft
from app.models.agent_task import AgentTask,AgentRun,AgentExecution

async def main():
    result=[]
    async with AsyncSessionLocal() as db:
        links=(await db.execute(select(ChatBillMessage,ChatBillAttachment,BillDocument).join(
            ChatBillAttachment,ChatBillAttachment.message_id==ChatBillMessage.id).join(
            BillDocument,BillDocument.id==ChatBillAttachment.document_id).where(
            BillDocument.filename.in_(['philixa-matching-test-bill.pdf','chat-intake-smoke.pdf'])))).all()
        for message,link,document in links:
            task=await db.get(AgentTask,message.task_id)
            drafts=(await db.scalars(select(PurchaseDraft).where(PurchaseDraft.document_id==document.id))).all()
            runs=(await db.scalars(select(AgentRun).where(AgentRun.task_id==task.id))).all()
            usage=[r.state['usage'] for r in runs if r.state.get('usage')]
            executions=(await db.scalars(select(AgentExecution).where(AgentExecution.task_id==task.id))).all()
            result.append({'task_id':task.id,'filename':document.filename,'document_id':document.id,
                'status':task.status,'revision':task.revision,'extraction_status':document.extraction_status,
                'extraction_generation':document.extraction_generation,'draft_count':len(drafts),
                'draft_ids':[d.id for d in drafts],'task_action_id':task.state.get('action_id'),
                'model_responses_with_usage':len(usage),'usage':usage,
                'tools':[e.data.get('tool') for e in executions],
                'created_at':task.created_at.isoformat(),'updated_at':task.updated_at.isoformat()})
    output=Path('output/chat-attachments-acceptance.json');output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'fixtures':result,'native_posting_performed':False},indent=2),encoding='utf-8')
    print(json.dumps({'fixtures':[{'filename':r['filename'],'draft_count':r['draft_count'],
        'model_responses':r['model_responses_with_usage'],'task_action_id':r['task_action_id']} for r in result]}))

if __name__=='__main__':asyncio.run(main())
