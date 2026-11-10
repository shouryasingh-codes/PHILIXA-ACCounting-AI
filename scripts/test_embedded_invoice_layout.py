"""Synthetic, vendor-independent table geometry; no model or native writes."""
import unittest,json
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.services.embedded_invoice_layout import page_invoice,extract_document


class Page:
    def __init__(self,invoice='TEST-A',total='118.00',scale=1,shift=0,service=False):
        self.words=[];self.labels={};self.service=service
        def word(x,y,text,width=20):self.words.append((x*scale+shift,y*scale,x*scale+shift+width*scale,(y+10)*scale,text,0,0,0))
        def field(label,y,value,x=30):
            self.labels[label]=[SimpleNamespace(x0=x*scale+shift,x1=(x+100)*scale+shift,y0=y*scale,y1=(y+10)*scale)]
            word(x+104,y,value,80)
        field('Invoice Number:',30,invoice)
        field('Invoice Date:',50,'08 Oct 2025')
        self.labels['Seller Details']=[SimpleNamespace(x0=30*scale+shift,x1=130*scale+shift,y0=80*scale,y1=90*scale)]
        word(30,95,'Synthetic Supplier',100)
        self.labels['Bill To:']=[SimpleNamespace(x0=300*scale+shift,x1=400*scale+shift,y0=80*scale,y1=90*scale)]
        word(300,95,'Synthetic Buyer',90)
        field('Nature of Supply:',130,'Service' if service else 'Goods')
        self.headers=['Qty','Gross','Discount','Other','Taxable','CGST','SGST/','IGST','Cess','Total']
        for index,label in enumerate(self.headers):word(30+index*55,200,label)
        word(30,225,'Synthetic product',120);word(30,240,'HSN: 12345678, 18% IGST',180)
        values=['1','150.00','32.00','0.00','100.00',None,None,'18.00',None,total]
        for index,value in enumerate(values):
            if value:word(30+index*55,260,value)
        word(30,285,'TOTAL')
        for index,value in enumerate(values[1:],1):
            if value:word(30+index*55,285,value)
    def get_text(self,mode=None):return self.words if mode=='words' else 'GSTIN Number: 29AAECM9636P1ZJ'
    def search_for(self,label):return self.labels.get(label,[])


class LayoutTests(unittest.TestCase):
    def test_column_values_and_missing_base_rate_preserved(self):
        info,lines=page_invoice(Page(),1)
        self.assertEqual(info['invoice_total'],'118.00');self.assertEqual(info['expected_taxes'],{'IGST':'18.00'})
        self.assertEqual(lines[0]['taxable_amount'],'100.00');self.assertIsNone(lines[0]['rate']);self.assertIsNone(lines[0]['unit'])
        self.assertEqual(lines[0]['source_evidence']['discount']['value'],'32.00')
    def test_independent_invoices_and_service_block(self):
        result=extract_document([Page(),Page(invoice='TEST-B',service=True)])
        self.assertTrue(result['multiple_invoices_detected']);self.assertIsNone(result['invoice_total'])
        self.assertEqual([group['page_numbers'] for group in result['detected_invoices']],[[1],[2]])
        self.assertIn('services',result['detected_invoices'][1]['unsupported_treatments'])
    def test_wrong_total_and_missing_column_abstain(self):
        self.assertIsNone(page_invoice(Page(total='119.00'),1))
        page=Page();page.words=[w for w in page.words if w[4]!='Taxable']
        self.assertIsNone(page_invoice(page,1))
    def test_unreadable_second_page_never_dropped(self):
        bad=Page(invoice='TEST-B');bad.words=[]
        self.assertIsNone(extract_document([Page(),bad]))
    def test_shifted_table_has_no_fixed_page_coordinates(self):
        info,_=page_invoice(Page(shift=14),1);self.assertEqual(info['invoice_total'],'118.00')


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_layout_result_does_not_call_paid_vision(self):
        from app.services.invoice_extraction import extract_invoice_data
        local={'_page_count':2,'_source_text':'readable','lines':[{'quantity':'1'}],
            'extraction_method':'embedded_layout','multiple_invoices_detected':True}
        async def parse(data,operation,page=None):return json.dumps(local).encode() if operation=='extract' else b'image'
        with patch('app.services.invoice_extraction.doc_service.parse',side_effect=parse),patch(
            'app.services.invoice_extraction.call_gemini_multimodal_extraction',AsyncMock(side_effect=AssertionError('No provider call'))) as provider:
            result=await extract_invoice_data(b'input','application/pdf')
            self.assertEqual(result['extraction_method'],'embedded_layout');provider.assert_not_awaited()

if __name__=='__main__':unittest.main()
