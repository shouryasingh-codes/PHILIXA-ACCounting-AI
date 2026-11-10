"""Durable authorization audit; all native posting transports are synthetic."""
import unittest
from sqlalchemy import select
from app.models.bill_evaluation import BillEvaluationMetric
from app.models.tally import TallyAction
from app.services import tally_sync as sync,purchase_draft_service as drafts
from scripts import test_purchase_automation as fixtures


class Authorization(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.EngineTests.asyncSetUp
    asyncTearDown=fixtures.EngineTests.asyncTearDown
    proof=fixtures.EngineTests.proof
    policy=fixtures.EngineTests.policy
    create=fixtures.EngineTests.create
    queued=fixtures.EngineTests.queued

    async def audit(self,action):
        events=list((await self.db.scalars(select(BillEvaluationMetric).where(
            BillEvaluationMetric.organization_id==self.org,BillEvaluationMetric.kind=='posting_authorized'))).all())
        self.assertEqual(len(events),1)
        self.assertEqual(events[0].data['action_id'],action.token)
        self.assertEqual(events[0].data['action_guid'],action.payload['guid'])
        self.assertEqual(events[0].data['actor_id'],self.user)
        self.assertEqual(len(events[0].data['approved_payload_sha256']),64)
        return events[0].data

    async def test_human_approval_audit_and_repeated_approval_one_event(self):
        row=await self.create()
        await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        row=await drafts.read_draft(self.db,self.principal,row['id'])
        action=await self.db.get(TallyAction,row['action_id'])
        await sync.confirm_queued(self.db,self.principal,action)
        await sync.confirm_queued(self.db,self.principal,action)
        data=await self.audit(action)
        self.assertEqual(data['authorization_type'],'human_approval')
        self.assertNotIn('policy_revision',data)
        from app.services.bill_evaluation_service import metrics
        exposed=(await metrics(self.db,self.principal,row['id']))['authorization_events']
        self.assertEqual(len(exposed),1)
        self.assertEqual(exposed[0]['action_id'],action.token)
        self.assertTrue(exposed[0]['recorded_at'])

    async def test_policy_audit_references_durable_decision_and_reservation(self):
        action=await self.queued()
        data=await self.audit(action)
        self.assertEqual(data['authorization_type'],'policy')
        self.assertEqual(data['policy_revision'],action.preconditions['automation']['policy_revision'])
        self.assertEqual(data['reservation_action_id'],action.token)
        self.assertTrue(data['decision_id'])

    async def test_policy_marker_without_durable_authorization_is_rejected(self):
        from app.services.posting_authorization import record_authorization
        from app.services.tally_connector import TallyError
        row=await self.create()
        await drafts.preview_draft(self.db,self.principal,row['id'],drafts.DraftPreview(revision=0))
        row=await drafts.read_draft(self.db,self.principal,row['id'])
        action=await self.db.get(TallyAction,row['action_id'])
        action.preconditions={**action.preconditions,'automation':{'policy_revision':999,'actor_id':self.user}}
        with self.assertRaisesRegex(TallyError,'Durable policy authorization'):
            await record_authorization(self.db,action,self.principal)
        self.assertEqual(list((await self.db.scalars(select(BillEvaluationMetric).where(
            BillEvaluationMetric.organization_id==self.org,BillEvaluationMetric.kind=='posting_authorized'))).all()),[])


if __name__=='__main__':unittest.main()
