"""Real PostgreSQL draft persistence and authorization; no Tally imports."""
import hashlib
import uuid
import unittest
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock
from sqlalchemy import delete,select,func
from fastapi import HTTPException
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.user import User
from app.models.organization_membership import OrganizationMembership
from app.models.tally import TallyDevice,TallyReadCompany,TallyAction
from app.services.business_command_service import ParsedCommand
from app.services import tally_mcp_service as service,tally_sync as sync
from app.services.tally_mcp import PIN
from app.services.tally_connector import TallyError

class Drafts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.org=uuid.uuid4().hex;self.user=uuid.uuid4().hex;self.db=AsyncSessionLocal()
        self.principal=SimpleNamespace(organization_id=self.org,user_id=self.user,session_id='mcp-test',role='owner')
        self.db.add(Organization(id=self.org,name='MCP draft test',slug=self.org))
        self.db.add(User(id=self.user,email=self.user+'@example.invalid',hashed_password='synthetic',is_active=True))
        await self.db.flush()
        self.db.add(OrganizationMembership(organization_id=self.org,user_id=self.user,role='owner',status='active'))
        self.device=TallyDevice(id=uuid.uuid4().hex,organization_id=self.org,credential_hash='a'*64,revoked=False)
        self.db.add(self.device);await self.db.flush()
        self.company=TallyReadCompany(id=uuid.uuid4().hex,organization_id=self.org,device_id=self.device.id,
            identity='test-company-identity',name='Isolated Test',enabled=True,aliases=[],member_ids=[],refresh_requested=False)
        self.db.add(self.company);await self.db.commit()
        self.parsed=ParsedCommand(intent='mcp_write',company_id=self.company.id,mcp_tool='create_godown',mcp_arguments={'name':'Test Godown'})
        self.env=patch.dict('os.environ',{'PHILIXA_MCP_READ_ENABLED':'1'});self.env.start()
    async def asyncTearDown(self):
        self.env.stop();await self.db.rollback()
        await self.db.execute(delete(TallyAction).where(TallyAction.organization_id==self.org))
        await self.db.execute(delete(Organization).where(Organization.id==self.org))
        await self.db.execute(delete(User).where(User.id==self.user));await self.db.commit();await self.db.close()
    async def draft(self):
        with patch.object(service,'request_job',AsyncMock(side_effect=TallyError('offline'))):
            result=await service.prepare_write(self.db,self.principal,self.parsed)
        self.assertFalse(result['preview']['can_confirm'])
        return await self.db.get(TallyAction,result['tally_action'])
    async def test_offline_draft_survives_new_session_and_cannot_execute(self):
        action=await self.draft();token=action.token;await self.db.close();self.db=AsyncSessionLocal()
        action=await self.db.get(TallyAction,token)
        self.assertEqual(action.payload['arguments'],{'name':'Test Godown'});self.assertEqual(action.status,'draft')
        with self.assertRaises(HTTPException) as error:await sync.confirm_queued(self.db,self.principal,action)
        self.assertEqual(error.exception.status_code,409)
        await sync.process_action(self.db,action,self.company);self.assertEqual(action.status,'draft')
    async def test_repeated_review_reuses_original_draft(self):
        action=await self.draft()
        with patch.object(service,'request_job',AsyncMock(side_effect=TallyError('offline'))):
            for _ in range(3):
                result=await service.review_write(self.db,self.principal,action)
                self.assertEqual(result['tally_action'],action.token)
        count=await self.db.scalar(select(func.count()).select_from(TallyAction).where(TallyAction.organization_id==self.org))
        self.assertEqual(count,1)
    async def test_forged_session_cannot_review_or_cancel(self):
        action=await self.draft();wrong=SimpleNamespace(**{**vars(self.principal),'session_id':'forged'})
        for operation in (service.review_write(self.db,wrong,action),sync.confirm_queued(self.db,wrong,action,approve=False)):
            with self.assertRaises(HTTPException) as error:await operation
            self.assertEqual(error.exception.status_code,410)
    async def test_cancelled_draft_cannot_be_recompiled(self):
        action=await self.draft();await sync.confirm_queued(self.db,self.principal,action,approve=False)
        self.assertEqual(action.status,'cancelled')
        with patch.object(service,'request_job',AsyncMock(side_effect=AssertionError('cancelled draft compiled'))):
            with self.assertRaises(HTTPException):await service.review_write(self.db,self.principal,action)
    async def test_compile_scope_mismatch_is_not_saved_as_valid_xml(self):
        action=await self.draft();xml='<ENVELOPE />'
        reply={'backend':'mcp','commit':PIN,'tool':'create_godown','company':'Wrong','identity':'test-company-identity',
            'posting_enabled':False,'xml':xml,'xml_sha256':hashlib.sha256(xml.encode()).hexdigest()}
        with patch.object(service,'request_job',AsyncMock(return_value=reply)):
            result=await service.review_write(self.db,self.principal,action)
        self.assertFalse(result['preview']['can_confirm']);self.assertEqual(action.xml_payload,'')
    async def test_explicit_company_even_if_only_one_approved(self):
        parsed=self.parsed.model_copy(update={'company_id':None})
        with patch.object(service,'request_job',AsyncMock(side_effect=AssertionError('company silently selected'))):
            result=await service.prepare_write(self.db,self.principal,parsed)
        self.assertEqual(result['tally_choices'][0]['command']['fields']['company_id'],self.company.id)

if __name__=='__main__':unittest.main()
