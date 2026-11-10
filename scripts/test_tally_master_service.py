"""Tests for Tally master creation (Supplier Ledgers, Stock Items, Units) and conversational auto-creation flow."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from xml.etree import ElementTree as ET
from app.services.tally_connector import parse_xml, TallyError
from app.services.tally_master_codec import (
    CREDITOR_GROUP,
    clean_stock_name,
    normalize_unit,
    validate_master_identity,
    build_unit_message,
    build_ledger_message,
    build_stock_item_message,
    batch_masters_xml,
)
from app.services.intent_router import is_create_masters_intent, fast_route
from app.services.tally_master_service import create_missing_masters_in_tally


class TestTallyMasterCodec(unittest.TestCase):
    def test_clean_stock_name(self):
        self.assertEqual(
            clean_stock_name("Processor Intel Core 13-10100 (10th Generation) (4-Core,6M Cache, 3.6GHz to 4.3GHz)"),
            "Processor Intel Core i3-10100 (10th Gen)"
        )
        self.assertEqual(
            clean_stock_name("Intel 410 Chip Set Mother board or higher with on-board graphics (GIGABYTE)"),
            "Intel 410 Chip Set Mother board or higher with on-board graphics (GIGABYTE)"
        )
        self.assertEqual(
            clean_stock_name('2.5" 240GB SATA II1 SSD HARD DRIVE (KINGSTON)'),
            '2.5" 240GB SATA II1 SSD HARD DRIVE (KINGSTON)'
        )

    def test_normalize_unit(self):
        self.assertEqual(normalize_unit("No"), "Nos")
        self.assertEqual(normalize_unit("Nos"), "Nos")
        self.assertEqual(normalize_unit("pcs"), "Pcs")
        self.assertEqual(normalize_unit("box"), "Box")
        self.assertEqual(normalize_unit(None), "Nos")
        self.assertEqual(normalize_unit("bags"), "bags")

    def test_validate_master_identity(self):
        self.assertEqual(validate_master_identity("  TimeNet Solutions  "), "TimeNet Solutions")
        with self.assertRaises(TallyError):
            validate_master_identity("")
        with self.assertRaises(TallyError):
            validate_master_identity("Bad\x01Name")

    def test_batch_masters_xml_generation_and_parsing(self):
        xml = batch_masters_xml(
            "Philixa Test",
            units=["Nos"],
            ledgers=[{
                "name": "TimeNet",
                "gstin": "32AACCT0612L1ZP",
                "state": "Kerala",
                "parent": CREDITOR_GROUP
            }],
            items=[{
                "name": "Processor Intel Core i3-10100 (10th Gen)",
                "unit": "Nos"
            }]
        )
        self.assertIn("SVCURRENTCOMPANY>Philixa Test<", xml)
        self.assertIn('<UNIT NAME="Nos" ACTION="Create">', xml)
        self.assertIn('<LEDGER NAME="TimeNet" ACTION="Create">', xml)
        self.assertIn("<PARENT>Sundry Creditors</PARENT>", xml)
        self.assertIn("<PARTYGSTIN>32AACCT0612L1ZP</PARTYGSTIN>", xml)
        self.assertIn('<STOCKITEM NAME="Processor Intel Core i3-10100 (10th Gen)" ACTION="Create">', xml)
        self.assertIn("<BASEUNITS>Nos</BASEUNITS>", xml)

        # Ensure XML is strictly well-formed
        root = ET.fromstring(xml.encode("utf-8"))
        self.assertEqual(root.tag, "ENVELOPE")
        msgs = root.findall(".//TALLYMESSAGE")
        self.assertEqual(len(msgs), 3)


class TestIntentRouterMasterCreation(unittest.TestCase):
    def test_is_create_masters_intent(self):
        self.assertTrue(is_create_masters_intent("Tally me Supplier aur Stock Items bana do"))
        self.assertTrue(is_create_masters_intent("✨ Tally me Supplier aur Stock Items bana do"))
        self.assertTrue(is_create_masters_intent("Tally me naye stock items bana do"))
        self.assertTrue(is_create_masters_intent("Tally me bana do"))
        self.assertTrue(is_create_masters_intent("haan bana do"))
        self.assertTrue(is_create_masters_intent("bana do"))
        self.assertTrue(is_create_masters_intent("create kar do"))
        self.assertTrue(is_create_masters_intent("tally me naye stock create kar do"))
        self.assertFalse(is_create_masters_intent("nahi mat banao"))
        self.assertFalse(is_create_masters_intent("Existing item se map karna hai"))
        self.assertFalse(is_create_masters_intent("stock kitna hai"))

    def test_fast_route_create_masters(self):
        ctx = {'task_id': 'a'*32, 'can_continue': True, 'draft_id': 'b'*32}
        decision = fast_route("Tally me Supplier aur Stock Items bana do", ctx)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.intent, 'bill_processing')
        self.assertEqual(decision.handler, 'domain_continuation')
        self.assertEqual(decision.target_task_id, 'a'*32)
        self.assertEqual(decision.target_draft_id, 'b'*32)
        self.assertEqual(decision.reason, 'fast_create_masters')


class TestMasterCreationService(unittest.IsolatedAsyncioTestCase):
    async def test_create_missing_masters_in_tally_flow(self):
        # Mock database, principal, draft and company
        mock_db = AsyncMock()
        mock_principal = SimpleNamespace(organization_id="org_test", user_id="usr_test", role="owner")
        mock_company = SimpleNamespace(id="comp_1", name="Philixa Test", identity="id_1")
        mock_draft = SimpleNamespace(
            id="draft_1",
            organization_id="org_test",
            user_id="usr_test",
            company_id="comp_1",
            content={
                "party_name": "TimeNet",
                "supplier_gstin": "32AACCT0612L1ZP",
                "lines": [
                    {
                        "item_name": "Processor Intel Core 13-10100 (10th Generation) (4-Core,6M Cache, 3.6GHz to 4.3GHz)",
                        "quantity": "12.00",
                        "unit": "No",
                        "rate": "9950.00"
                    }
                ]
            },
            extraction_metadata={},
            revision=1,
            action_id=None,
            updated_at=None
        )

        with patch("app.services.purchase_draft_service.scoped_draft", AsyncMock(return_value=mock_draft)), \
             patch("app.services.purchase_draft_service.company_for", AsyncMock(return_value=mock_company)), \
             patch("app.services.tally_sync.saved_snapshot", AsyncMock(return_value=None)), \
             patch("app.services.tally_connector.TallyConnector.catalog", AsyncMock(return_value={'ledgers': [], 'units': [], 'items': []})), \
             patch("app.services.tally_connector.TallyConnector.post", AsyncMock(return_value=ET.fromstring("<RESPONSE><CREATED>3</CREATED><ERRORS>0</ERRORS></RESPONSE>"))), \
             patch("app.services.tally_sync.refresh_company", AsyncMock(return_value=True)), \
             patch("app.services.purchase_draft_service.record_event", lambda *a, **k: None), \
             patch("app.services.purchase_situation.state", AsyncMock(return_value={"proposal": {"content": mock_draft.content}, "issues": [], "can_preview": True})):

            result = await create_missing_masters_in_tally(
                mock_db, mock_principal, "draft_1", create_supplier=True, create_items=True
            )

            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['supplier_created'], 'TimeNet')
            self.assertEqual(result['units_created'], ['Nos'])
            self.assertEqual(result['items_created'], ['Processor Intel Core i3-10100 (10th Gen)'])
            self.assertIn("Maine Tally me TimeNet (Sundry Creditors) aur 1 stock items create kar diye hain!", result['response'])
            self.assertEqual(mock_draft.content['lines'][0]['item_name'], 'Processor Intel Core i3-10100 (10th Gen)')
            self.assertEqual(mock_draft.content['lines'][0]['unit'], 'Nos')


if __name__ == "__main__":
    unittest.main()
