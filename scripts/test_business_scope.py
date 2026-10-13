"""Real DB/Redis scope checks with mocked message transport. No email or WhatsApp is sent."""
import asyncio, uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException
from sqlalchemy import select, delete
from app.models.communication_log import CommunicationLog
from app.services import business_command_service as b
from app.api.v1.routes_business import command
from app.database.session import AsyncSessionLocal
from app.models.client import Client
from app.models.commitment import Commitment
from app.repositories.client_repository import ClientRepository
from app.repositories.commitment_repository import CommitmentRepository

async def rejects(awaitable,status):
    try: await awaitable
    except HTTPException as error:
        assert error.status_code==status,(error.status_code,error.detail); return
    raise AssertionError('Expected rejection')

async def main():
    configured = dict(smtp_hostname='smtp.test.invalid', smtp_from_address='from@test.invalid',
                      smtp_username='test', smtp_password='test',
                      whatsapp_phone_number_id='test', whatsapp_access_token='test')
    destinations = dict(wants_email=True, wants_whatsapp=True,
                        email_destination='to@test.invalid', whatsapp_destination='+919000000000')
    with patch.object(b, 'get_settings', return_value=SimpleNamespace(**configured)):
        assert b.delivery_blockers(destinations) == []
        assert len(b.delivery_blockers(dict(wants_email=True, wants_whatsapp=True))) == 2
    for field in configured:
        with patch.object(b, 'get_settings', return_value=SimpleNamespace(**{**configured, field: ''})):
            assert b.delivery_blockers(destinations), field
    print('PASS: configured channels enabled; missing credentials or recipients blocked')
    import httpx
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=30) as setup:
        seeded=await setup.post('/api/v1/auth/demo-login')
        seeded.raise_for_status()
    async with AsyncSessionLocal() as db:
        seed=await db.scalar(select(Client).order_by(Client.id).limit(1))
        assert seed
        p=SimpleNamespace(organization_id=seed.organization_id,user_id=seed.user_id,role='owner',session_id='business-test-scope')
        client=await ClientRepository().create(db,p,{'name':'Scoped test '+uuid.uuid4().hex[:8],'email':'scope@example.invalid','whatsapp_phone':'+919000000000'})
        await db.commit(); await db.refresh(client)
        client_id=client.id
        try:
            cross=SimpleNamespace(**{**p.__dict__,'organization_id':'unrelated-org'})
            member=SimpleNamespace(**{**p.__dict__,'user_id':'unrelated-user','role':'member'})
            read=b.CommandRequest(intent='customer_read',client_id=client_id)
            await rejects(command(read,cross,db),404)
            await rejects(command(read,member,db),404)
            other=await ClientRepository().create(db,p,{'name':client.name+' branch'}); await db.commit()
            ambiguous=await command(b.CommandRequest(intent='customer_read',fields={'client_name':'Scoped test'}),p,db)
            assert len(ambiguous['choices'])>=2
            await ClientRepository().delete(db,p,other.id); await db.commit()
            future=(b.today()+timedelta(days=1)).isoformat()
            pending=await command(b.CommandRequest(intent='task_create',client_id=client_id,fields={'description':'Scoped test task','due_date':future}),p,db)
            token=pending['preview']['token']
            await rejects(b.confirm(b.ApprovalRequest(token=token,approve=True),cross,db),410)
            await rejects(b.confirm(b.ApprovalRequest(token=token,approve=True),member,db),410)
            done=await b.confirm(b.ApprovalRequest(token=token,approve=True),p,db)
            overdue=await CommitmentRepository().create(db,p,{'client_id':client_id,'description':'Overdue scope fixture','due_date':b.today()-timedelta(days=1),'owner':'Business user'})
            await db.commit()
            overdue_rows=await command(b.CommandRequest(intent='task_list',fields={'when':'overdue'}),p,db)
            assert any(t['id']==overdue.id and t['overdue'] for t in overdue_rows['tasks'])
            assert not any(t['id']==done['task_id'] for t in overdue_rows['tasks'])
            today_rows=await command(b.CommandRequest(intent='task_list',fields={'when':'today'}),p,db)
            assert any(t['id']==overdue.id for t in today_rows['tasks']) and not any(t['id']==done['task_id'] for t in today_rows['tasks'])
            await rejects(command(b.CommandRequest(intent='task_complete',fields={'task_id':done['task_id']}),cross,db),404)
            await rejects(command(b.CommandRequest(intent='task_complete',fields={'task_id':done['task_id']}),member,db),404)
            # Customer data changed after preview: refuse the stale approval.
            stale=await command(b.CommandRequest(intent='customer_update',client_id=client_id,fields={'email':'changed@example.invalid'}),p,db)
            await ClientRepository().update(db,p,client_id,{'whatsapp_phone':'+919000000001'}); await db.commit()
            await rejects(b.confirm(b.ApprovalRequest(token=stale['preview']['token'],approve=True),p,db),409)
            # Test send confirmation with a mock transport only.
            drafted={'email_subject':'Test','email_body':'Test email','whatsapp_body':'Test WhatsApp'}
            with patch.object(b.ReminderService,'_draft_messages',new=AsyncMock(return_value=drafted)), patch.object(b,'delivery_blockers',return_value=[]):
                preview=await command(b.CommandRequest(intent='reminder_draft',client_id=client_id,fields={'description':'test message','channel':'email'}),p,db)
                dispatch=AsyncMock(return_value={'message':'Mock delivery accepted','status':'success'})
                with patch.object(b.ReminderService,'dispatch_client_reminder',new=dispatch):
                    first=await b.confirm(b.ApprovalRequest(token=preview['preview']['token'],approve=True),p,db)
                    second=await b.confirm(b.ApprovalRequest(token=preview['preview']['token'],approve=True),p,db)
                    assert first==second and dispatch.await_count==1
                        # Exercise the real reminder service and communication logging with mocked adapters.
            with patch.object(b.ReminderService,'_draft_messages',new=AsyncMock(return_value=drafted)), patch.object(b,'delivery_blockers',return_value=[]):
                preview=await command(b.CommandRequest(intent='reminder_draft',client_id=client_id,fields={'description':'test transport','channel':'email'}),p,db)
                email=AsyncMock(return_value={'status':'sent','provider_message_id':'mock-email'})
                wa=AsyncMock()
                with patch('app.services.notifications.email_adapter.EmailAdapter.send_message',new=email), patch('app.services.notifications.whatsapp_adapter.WhatsAppAdapter.send_message',new=wa):
                    result=await b.confirm(b.ApprovalRequest(token=preview['preview']['token'],approve=True),p,db)
                    assert result['delivery_status']=='success' and email.await_count==1 and wa.await_count==0
                log=await db.scalar(select(CommunicationLog).where(CommunicationLog.client_id==client_id))
                assert log and log.provider_message_id=='mock-email'
            print('PASS: tenant/member scope, ambiguous names, scoped approvals, stale previews, reminder confirms exactly once with mocked transport')
        finally:
            await db.rollback()
            await db.execute(delete(CommunicationLog).where(CommunicationLog.client_id==client_id))
            await ClientRepository().delete(db,p,client_id); await db.commit()
            print('Removed scope test records')
asyncio.run(main())
