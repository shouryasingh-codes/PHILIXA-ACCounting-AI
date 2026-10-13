"""Database chat persistence, ownership and revision tests. No model/Tally calls."""
import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from app.models.tally import TallyAction
from app.services import business_conversation_service as chats
import scripts.test_tally_sync as fixtures


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DurableTests.asyncSetUp
    asyncTearDown=fixtures.DurableTests.asyncTearDown

    async def create(self):
        return await chats.create_conversation(self.db,self.principal,chats.ConversationCreate(organization_id=self.org))

    async def test_two_chats_remain_saved_and_reopen_without_actions(self):
        first=await self.create()
        await chats.save_conversation(self.db,self.principal,first['id'],chats.ConversationSave(revision=0,messages=[
            {'role':'user','text':'Cement purchase'},
            {'role':'assistant','text':'Check details','data':{'preview':{'token':'untrusted','can_confirm':True}}}]))
        second=await self.create()
        listing=await chats.list_conversations(self.db,self.principal)
        self.assertEqual([row['id'] for row in listing['conversations']],[second['id'],first['id']])
        self.assertEqual(listing['conversations'][1]['title'],'Cement purchase')
        restored=await chats.read_conversation(self.db,self.principal,first['id'])
        self.assertEqual(len(restored['messages']),2)
        actions=list((await self.db.scalars(select(TallyAction).where(TallyAction.organization_id==self.org))).all())
        self.assertEqual(actions,[],'Transcript metadata cannot create/approve an accounting action')

    async def test_chats_are_private_to_user_and_workspace(self):
        created=await self.create()
        for changes in ({'user_id':'another-user'},{'organization_id':'another-workspace'}):
            other=SimpleNamespace(**{**self.principal.__dict__,**changes})
            self.assertEqual((await chats.list_conversations(self.db,other))['conversations'],[])
            for operation in (chats.read_conversation(self.db,other,created['id']),
                chats.save_conversation(self.db,other,created['id'],chats.ConversationSave(revision=0,messages=[]))):
                with self.assertRaises(HTTPException) as error:await operation
                self.assertEqual(error.exception.status_code,404)

    async def test_stale_revision_cannot_overwrite_new_messages(self):
        created=await self.create()
        updated=await chats.save_conversation(self.db,self.principal,created['id'],chats.ConversationSave(revision=0,messages=[{'role':'user','text':'Latest'}]))
        self.assertEqual(updated['revision'],1)
        with self.assertRaises(HTTPException) as error:
            await chats.save_conversation(self.db,self.principal,created['id'],chats.ConversationSave(revision=0,messages=[{'role':'user','text':'Stale'}]))
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual((await chats.read_conversation(self.db,self.principal,created['id']))['messages'][0]['text'],'Latest')

    async def test_new_login_disables_old_preview_without_changing_saved_record(self):
        created=await self.create()
        await chats.save_conversation(self.db,self.principal,created['id'],chats.ConversationSave(revision=0,messages=[
            {'role':'assistant','text':'Preview','data':{'preview':{'token':'old','can_confirm':True}}}]))
        other=SimpleNamespace(**{**self.principal.__dict__,'session_id':'new-login'})
        old=await chats.read_conversation(self.db,other,created['id'])
        self.assertFalse(old['messages'][0]['data']['preview']['can_confirm'])
        current=await chats.read_conversation(self.db,self.principal,created['id'])
        self.assertTrue(current['messages'][0]['data']['preview']['can_confirm'])

    async def test_create_rejects_changed_workspace(self):
        with self.assertRaises(HTTPException) as error:
            await chats.create_conversation(self.db,self.principal,chats.ConversationCreate(organization_id='other'))
        self.assertEqual(error.exception.status_code,409)


if __name__=='__main__':unittest.main()
