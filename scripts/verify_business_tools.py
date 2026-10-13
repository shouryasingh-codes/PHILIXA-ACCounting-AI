"""Integration checks against duplicate app. Creates and removes its own test customer only."""
import asyncio, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from app.api.v1.routes_business import delivery_blockers

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",timeout=100) as c:
        r=await c.post('/api/v1/business/command',json={'intent':'customer_list'})
        assert r.status_code in (401,403)
        login=await c.post('/api/v1/auth/demo-login'); login.raise_for_status()
        c.headers['X-CSRF-Token']=login.json().get('csrf_token') or c.cookies.get('csrf_token')
        customer_id=None
        async def command(intent,fields=None,client_id=None,text=''):
            r=await c.post('/api/v1/business/command',json={'intent':intent,'fields':fields or {},'client_id':client_id,'text':text})
            r.raise_for_status(); return r.json()
        async def confirm(token,approve=True):
            r=await c.post('/api/v1/business/confirm',json={'token':token,'approve':approve})
            r.raise_for_status(); return r.json()
        try:
            name='Business test '+uuid.uuid4().hex[:8]
            preview=await command('customer_create',{'client_name':name,'email':'test@example.invalid','whatsapp_phone':'+919000000000'})
            assert not any(x['name']==name for x in (await command('customer_list'))['choices'])
            saved=await confirm(preview['preview']['token']); customer_id=saved['customer_id']
            assert (await confirm(preview['preview']['token']))['customer_id']==customer_id
            detail=await command('customer_read',client_id=customer_id)
            assert '+919000000000' in detail['response'] and 'koi meeting' in detail['response']
            due=(datetime.now(ZoneInfo('Asia/Kolkata')).date()+timedelta(days=1)).isoformat()
            task=await command('task_create',{'description':'Payment follow-up integration test','due_date':due},customer_id)
            before=await command('task_list')
            assert not any(t['customer']==name for t in before['tasks'])
            saved=await confirm(task['preview']['token']); task_id=saved['task_id']
            assert (await confirm(task['preview']['token']))['task_id']==task_id
            after=await command('task_list'); assert sum(t['id']==task_id for t in after['tasks'])==1
            assert not any(t['id']==task_id for t in (await command('task_list',{'when':'today'}))['tasks'])
            taskdone=await command('task_complete',{'task_id':task_id}); await confirm(taskdone['preview']['token'])
            assert not any(t['id']==task_id for t in (await command('task_list'))['tasks'])
            update=await command('customer_update',{'email':'new@example.invalid'},customer_id)
            await confirm(update['preview']['token'])
            assert 'new@example.invalid' in (await command('customer_read',client_id=customer_id))['response']
            cancelled=await command('task_create',{'description':'Must not save','due_date':due},customer_id)
            await confirm(cancelled['preview']['token'],False)
            assert not any(t['description']=='Must not save' for t in (await command('task_list'))['tasks'])
            reminder=await command('reminder_draft',{'description':'Please confirm the payment update','channel':'email'},customer_id)
            expected_blockers=delivery_blockers({'wants_email':True,'email_destination':'new@example.invalid'})
            assert reminder['preview']['blockers']==expected_blockers
            assert reminder['preview']['can_confirm']==(not expected_blockers)
            # Always cancel: integration verification must never dispatch to a real provider.
            await confirm(reminder['preview']['token'],False)
            for channel in ('whatsapp', 'both'):
                reminder=await command('reminder_draft',{'description':'Please confirm the payment update','channel':channel},customer_id)
                expected_blockers=delivery_blockers({'wants_email':channel=='both','wants_whatsapp':True,
                                                    'email_destination':'new@example.invalid','whatsapp_destination':'+919000000000'})
                assert reminder['preview']['blockers']==expected_blockers
                assert reminder['preview']['can_confirm']==(not expected_blockers)
                await confirm(reminder['preview']['token'],False)
            print('PASS: auth, preview-before-write, customer read/update, task create/list/complete, cancel, repeat confirmation, configured delivery preview (no send)')
            # Exercise real natural-language interpretation without actually sending any message.
            parsed=await c.post('/api/v1/business/command',json={'text':f'{name} se kal payment ke liye follow-up karna'})
            parsed.raise_for_status(); data=parsed.json()
            assert data.get('preview') and due in '\n'.join(data['preview']['lines']), data
            await confirm(data['preview']['token'],False)
            print('PASS: Hinglish instruction -> scoped customer -> tomorrow task preview')
            hindi=await c.post('/api/v1/business/command',json={'text':'राजेश शर्मा का नंबर और पिछली बात बताओ'})
            hindi.raise_for_status(); result=hindi.json()
            assert result.get('customer',{}).get('name')=='Rajesh Sharma',result
            print('PASS: Hindi-script customer name resolves to stored contact/memory')
        finally:
            if customer_id:
                cleaned=await c.delete(f'/api/v1/clients/{customer_id}'); cleaned.raise_for_status()
                print('Removed test customer and related test tasks')

asyncio.run(main())
