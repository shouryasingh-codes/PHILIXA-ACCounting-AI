import json
import unittest
from app.services.tally_connector import TallyError
from app.services.tally_mcp_reports import dates,display,report_catalog,LABELS
from app.services.tally_mcp import CONTRACTS

def reply(value):return {'content':[{'type':'text','text':json.dumps(value)}]}

class Reports(unittest.TestCase):
    def purchase(self,period='October',debit='-5950',credit='',net='-5950'):
        return {'ENVELOPE':{'DSPPERIOD':period,'DSPACCINFO':{'DSPDRAMT':{'DSPDRAMTA':debit},'DSPCRAMT':{'DSPCRAMTA':credit},'DSPCLAMT':{'DSPCLAMTA':net}}}}
    def test_native_purchase_monthly_summary_readable(self):
        view=display(reply(self.purchase()),'get_purchase_register')
        self.assertEqual(view['rows'],[['October','₹5,950.00','','₹-5,950.00']])
        self.assertEqual(view['columns'],['Month','Debit amount','Credit amount','Net amount (Tally signed)'])
        self.assertIn('not individual vouchers',view['note'])
    def test_purchase_precision_zero_and_credit_are_preserved(self):
        view=display(reply(self.purchase(debit='-123456789012345.1234',credit='0',net='0')),'get_purchase_register')
        self.assertEqual(view['rows'][0][1:],['₹123,456,789,012,345.1234','₹0.00','₹0.00'])
    def test_purchase_multiple_months_require_matching_columns(self):
        value=self.purchase();entry=value['ENVELOPE']['DSPACCINFO']
        value['ENVELOPE']['DSPPERIOD']=['October','November']
        with self.assertRaises(TallyError):display(reply(value),'get_purchase_register')
        value['ENVELOPE']['DSPACCINFO']=[entry,entry]
        self.assertEqual(display(reply(value),'get_purchase_register')['total_rows'],2)
    def test_purchase_invalid_amount_or_missing_column_blocks(self):
        for value in (self.purchase(debit='NaN'),self.purchase(debit='1e9'),{'ENVELOPE':{'DSPPERIOD':'October'}}):
            with self.assertRaises(TallyError):display(reply(value),'get_purchase_register')
    def test_every_read_has_a_label_and_form_contract(self):
        expected={k for k,v in CONTRACTS.items() if v['category']=='read'}
        self.assertEqual(expected,set(LABELS));self.assertEqual(len(report_catalog()),26)
    def test_dates_explicit_and_ordered(self):
        self.assertEqual(dates({'from':'2026-04-01','to':'09-10-2026'}),{'from':'01-04-2026','to':'09-10-2026'})
        self.assertEqual(dates({}),{})
        for args in ({'asOf':'31-02-2026'},{'asOf':'today'},{'from':'2026-10-10','to':'2026-10-09'}):
            with self.assertRaises(TallyError):dates(args)
    def test_native_master_rows_and_financial_strings(self):
        result=display(reply({'DATA':{'ROW':[{'NAME':'Cash','CLOSINGBALANCE':'123456789012345.12'},{'NAME':'Supplier','CLOSINGBALANCE':0}]}}),'get_ledgers')
        self.assertEqual(result['total_rows'],2);self.assertEqual(result['rows'][0][1],'123456789012345.12')
    def test_empty_rows_do_not_claim_zero_balances(self):
        result=display(reply({'rows':[]}),'get_stock_summary');self.assertEqual(result['rows'],[])
    def test_balance_sheet_never_pairs_mismatching_arrays(self):
        with self.assertRaises(TallyError):display(reply({'ENVELOPE':{'BSNAME':[{},{}],'BSAMT':[{}]}}),'get_balance_sheet')
    def test_tally_zero_amount_is_preserved(self):
        result=display(reply({'ENVELOPE':{'BSNAME':[{'DSPACCNAME':{'DSPDISPNAME':'Cash'}}],'BSAMT':[{'BSMAINAMT':0,'BSSUBAMT':99}]}}),'get_balance_sheet')
        self.assertEqual(result['rows'][0][1],'0')
    def test_error_payload_not_report(self):
        for value in ({'ENVELOPE':{'LINEERROR':'invalid'}},{'ERROR':'rejected'}):
            with self.assertRaises(TallyError):display(reply(value),'get_ledgers')
    def test_unstructured_reply_rejected(self):
        with self.assertRaises(TallyError):display({'content':[{'type':'text','text':'not a report'}]},'get_ledgers')
    def test_unknown_nested_shape_keeps_source_values(self):
        result=display(reply({'ENVELOPE':{'DATA':{'Amounts':[10,20]}}}),'get_cash_flow')
        self.assertEqual(result['rows'],[['["10", "20"]']])

if __name__=='__main__':unittest.main()
