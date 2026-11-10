import unittest
from app.services.repeat_purchase import proposal
from app.services.task_agent_selection import confirmation_offer

class RepeatTests(unittest.TestCase):
    def test_current_quantity_old_rate_and_no_old_invoice_facts(self):
        content={'lines':[{'item_name':'Cement','quantity':'5','unit':'bags','rate':None}]}
        context={'status':'ready','supplier_suggestion':{'supplier':'Sharma Traders','rates':[
            {'field':'0:rate','value':'350','entry_date':'2026-10-02','invoice_number':'OLD-1'}]}}
        result=proposal(content,context)
        self.assertEqual(result['subtotal_before_discount_tax'],'1750.00')
        self.assertEqual(result['lines'][0]['quantity'],'5')
        self.assertEqual(result['confirmation_scope'],'supplier_and_suggested_rates_only')
        self.assertNotIn('invoice_number',result)
        self.assertNotIn('entry_date',result)
        self.assertIsNone(content['lines'][0]['rate'])

    def test_incomplete_history_abstains_and_explicit_price_wins(self):
        c={'party_name':'Sharma','lines':[{'item_name':'Cement','quantity':'5','unit':'bags','rate':'380'}]}
        r={'status':'ready','suggestions':[{'field':'0:rate','value':'350'}]}
        result=proposal(c,r)
        self.assertEqual(result['subtotal_before_discount_tax'],'1900.00')
        self.assertIsNone(proposal(c,{**r,'status':'error'}))

    def test_done_never_authorises_posting_or_ambiguous_choices(self):
        self.assertIsNone(confirmation_offer([],'done'))
        self.assertIsNone(confirmation_offer([{'kind':'identity'}],'done'))
        self.assertIsNone(confirmation_offer([{'kind':'rate'},{'kind':'rate'}],'done'))
        history={'kind':'history'}
        self.assertEqual(confirmation_offer([history],'done'),history)
        self.assertIsNone(confirmation_offer([history],'done but rate 380'))

if __name__=='__main__':unittest.main()
