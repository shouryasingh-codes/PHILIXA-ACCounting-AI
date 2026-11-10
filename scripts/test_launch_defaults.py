"""Launch is reviewed/test-only. No real-company posting enablement is implied."""
import unittest
import uuid
from unittest.mock import AsyncMock,patch
from app.api.v1.routes_tally import ConnectionRequest
from app.services import tally_sync as sync,purchase_automation_service as automation
from app.services.tally_sync_protocol import validate_purchase
from app.services.tally_gst_purchase import compile_purchase
from app.services.tally_connector import TallyError
from scripts import test_tally_sync as fixtures


class Defaults(unittest.TestCase):
    def test_connection_and_policy_defaults_do_not_enable_writes(self):
        request=ConnectionRequest(company='Example',godown='Main',purchase_ledger='Purchase',sales_ledger='Sales')
        self.assertFalse(request.test_company)
        self.assertEqual(automation.PolicySave(revision=0).mode,'paused')

    def test_helper_rejects_non_test_configuration_before_catalog_or_import(self):
        payload={key:'synthetic' for key in ('company','godown','party','item','quantity','unit','rate','total','voucher_type','ledger','date','guid','stock_before','master_fingerprint')}
        payload['voucher_type']='Purchase'
        config=dict(company='Example',godown='Main',purchase_ledger='Purchase',sales_ledger='Sales',test_company=False)
        with self.assertRaisesRegex(TallyError,'Test company authorization'):
            validate_purchase({},payload,config)

    def test_gst_real_company_configuration_cannot_compile(self):
        with self.assertRaisesRegex(TallyError,'test company'):
            compile_purchase({}, {}, {}, {'test_company':False},str(uuid.uuid4()))


class ReviewedLaunch(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.DurableTests.asyncSetUp
    asyncTearDown=fixtures.DurableTests.asyncTearDown
    preview=fixtures.DurableTests.preview

    async def test_no_policy_defaults_to_review_without_auto_enablement(self):
        view=await automation.policy_view(self.db,self.principal,self.company.id)
        self.assertEqual(view['policy']['mode'],'paused')
        self.assertFalse(view['enabled'])

    async def test_non_test_configuration_stops_even_previously_approved_dispatch(self):
        action=await self.preview()
        await sync.confirm_queued(self.db,self.principal,action)
        self.cfg.test_company=False;await self.db.commit()
        with patch.object(sync,'operation',AsyncMock()) as operation:
            await sync.process_action(self.db,action,self.company)
            operation.assert_not_awaited()
        self.assertEqual(action.status,'needs_review')


if __name__=='__main__':unittest.main()
