"""Accounting semantic checks: strict schemas alone cannot establish validity."""
import unittest
from datetime import date
from app.services.tally_mcp_write_validation import validate_write
from app.services.tally_connector import TallyError

TODAY = date(2026, 10, 9)

class Semantics(unittest.TestCase):
    def voucher(self, **fields):
        return {'voucherType':'Journal','date':'09-10-2026',**fields}
    def check(self,tool,args):return validate_write(tool,args,today=TODAY)
    def reject(self,tool,args):
        with self.assertRaises(TallyError):self.check(tool,args)
    def test_balanced_decimal_entries_without_float_rounding(self):
        self.check('create_voucher',self.voucher(entries=[
            {'ledgerName':'A','amount':0.1,'type':'debit'},
            {'ledgerName':'B','amount':0.2,'type':'debit'},
            {'ledgerName':'C','amount':0.3,'type':'credit'}]))
    def test_unbalanced_or_signed_input_cannot_compile(self):
        for value in (0.29,-0.3,0):
            self.reject('create_voucher',self.voucher(entries=[
                {'ledgerName':'A','amount':0.3,'type':'debit'},
                {'ledgerName':'B','amount':value,'type':'credit'}]))
    def test_missing_and_empty_accounting_entries(self):
        for fields in ({},{'entries':[]},{'entries':[{'ledgerName':'A','amount':1,'type':'debit'}]}):
            self.reject('create_voucher',self.voucher(**fields))
    def test_minor_unit_precision(self):
        self.reject('create_voucher',self.voucher(debitLedger='A',creditLedger='B',amount=0.001))
    def test_invalid_date_cannot_roll_over_in_javascript(self):
        for value in ('31-02-2026','2026-10-09','10-10-2026'):
            self.reject('create_voucher',self.voucher(date=value,debitLedger='A',creditLedger='B',amount=1))
    def test_arbitrary_xml_fields_cannot_enter_typed_builder(self):
        self.reject('create_ledger',{'name':'A','parent':'Sundry Creditors','extraFields':{'GUID':'override'}})
    def test_blank_master_name(self):
        self.reject('create_godown',{'name':'  '})
    def test_empty_stock_transaction(self):
        self.reject('create_sales_invoice',{'date':'09-10-2026','partyLedger':'A','items':[]})
    def test_physical_count_zero_and_expired_date(self):
        args={'date':'09-10-2026','items':[{'stockItem':'Cement','actualQty':0,'unit':'bags','godown':'Main Location'}]}
        self.check('create_physical_stock',args)
        self.reject('create_physical_stock',{**args,'date':'01-10-2026'})
        self.reject('create_physical_stock',{**args,'items':[{**args['items'][0],'actualQty':-1}]})
    def test_batch_checks_every_voucher(self):
        good=self.voucher(debitLedger='A',creditLedger='B',amount=1,narration='Batch 1')
        self.check('create_vouchers_batch',{'vouchers':[good]})
        self.reject('create_vouchers_batch',{'vouchers':[good,self.voucher(narration='Batch 2')]})
        self.reject('create_vouchers_batch',{'vouchers':[good,good]})
    def test_narration_only_edit_is_draftable_not_authorized(self):
        self.check('update_voucher',self.voucher(voucherNumber='1',narration='Corrected spelling'))
        self.reject('create_voucher',self.voucher(narration='Only a note'))

if __name__=='__main__':unittest.main()
