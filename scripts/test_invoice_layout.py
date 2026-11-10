import copy
import json
import unittest
from unittest.mock import patch, AsyncMock
from app.services.invoice_layout import normalize, GridParser
from app.services.invoice_layout_review import Meaning, resolve, payload
from app.services.ocr_semantic_invoice import Header, Line


def fixture():
    html='<table><tr><td>Description</td><td>Qty</td><td>Rate</td><td>Amount</td></tr><tr><td>Bolts</td><td>2 bags</td><td>100</td><td>200</td></tr></table>'
    cells=[[10+c*100,100+r*30,100+c*100,125+r*30] for r in range(2) for c in range(4)]
    result={'table_res_list':[{'pred_html':html,'cell_box_list':cells}],
            'overall_ocr_res':{'rec_texts':['Vendor A','Buyer A','INV-1','02 Nov 2026','200'],
            'rec_boxes':[[10,10+i*15,90,22+i*15] for i in range(5)]}}
    result['overall_ocr_res']['rec_texts'] += ['Description','Qty','Rate','Amount','Bolts','2 bags','100','200']
    result['overall_ocr_res']['rec_boxes'] += cells
    layout=normalize(result,b'original',500,500,{'version':'test'})
    h={k:[] for k in Header.model_fields};h.update(supplier=[0],buyer=[1],invoice_number=[2],invoice_date=[3],invoice_total=[4],subtotal=[4])
    line={k:[] for k in Line.model_fields if k!='amount_basis'}
    line.update(description=[9],quantity=[10],unit=[10],rate=[11],amount=[12],amount_basis='before_tax',table_id='t0',row=1)
    selected=dict(document_kind='invoice',single_invoice=True,header=h,
                  rows=[dict(table_id='t0',row=0,kind='header'),dict(table_id='t0',row=1,kind='item')],lines=[line],taxes=[])
    return layout,selected,result


class LayoutTests(unittest.TestCase):
    def test_source_values_and_crops(self):
        layout,selection,_=fixture();raw=resolve(layout,selection)
        self.assertEqual(raw['lines'][0]['rate'],'100')
        self.assertEqual(raw['lines'][0]['unit'],'bags')
        self.assertEqual(raw['lines'][0]['source_evidence']['rate']['bbox'],[210,130,300,155])
        self.assertFalse(raw['posting_allowed'])

    def test_flat_transport_preserves_rows_and_checks_lengths(self):
        from app.services.invoice_layout_review import FlatMeaning,selection_from_wire
        layout,selection,_=fixture()
        flat={k:[] for k in FlatMeaning.model_fields}
        flat.update(document_kind='invoice',single_invoice=True,row_kinds=['header','item'],item_amount_basis=['before_tax'])
        flat.update({'header_'+k:v for k,v in selection['header'].items()})
        flat.update({'item_'+k:[selection['lines'][0][k]] for k in Line.model_fields if k!='amount_basis'})
        chosen=selection_from_wire(layout,flat)
        self.assertEqual(chosen.lines[0].row,1)
        self.assertEqual(chosen.lines[0].quantity,[10])
        self.assertEqual(resolve(layout,chosen)['lines'][0]['rate'],'100')
        flat['item_rate']=[]
        with self.assertRaisesRegex(ValueError,'array coverage'):selection_from_wire(layout,flat)

    def test_column_samples_expand_source_rows_without_model_values(self):
        from app.services.invoice_layout_review import ColumnMeaning,selection_from_wire
        layout,selection,_=fixture()
        wire={k:[] for k in ColumnMeaning.model_fields}
        wire.update(document_kind='invoice',single_invoice=True,row_kinds=['header','item'],amount_basis='before_tax',
                    sample_description=[9],sample_quantity=[10],sample_unit=[10],sample_rate=[11],sample_amount=[12])
        wire.update({'header_'+k:v for k,v in selection['header'].items()})
        chosen=selection_from_wire(layout,wire)
        self.assertEqual(resolve(layout,chosen)['lines'][0]['amount'],'200')
        wire['sample_rate']=[11,12]
        with self.assertRaises(ValueError):selection_from_wire(layout,wire)
        wire['sample_rate']=[10]
        with self.assertRaisesRegex(ValueError,'Conflicting'):selection_from_wire(layout,wire)
        wire['sample_rate']=[11];wire['sample_quantity']=[6]
        with self.assertRaisesRegex(ValueError,'item cell'):selection_from_wire(layout,wire)

    def test_column_indices_resolve_all_rows_and_reject_source_ids(self):
        from app.services.invoice_layout_review import ColumnRoles,selection_from_wire
        layout,selection,_=fixture()
        wire={k:[] for k in ColumnRoles.model_fields}
        wire.update(document_kind='invoice',single_invoice=True,table_id='t0',row_kinds=['header','item'],amount_basis='before_tax',column_description=[0],column_quantity=[1],column_rate=[2],column_amount=[3])
        wire.update({'header_'+k:v for k,v in selection['header'].items()})
        result=resolve(layout,selection_from_wire(layout,wire))
        self.assertEqual(result['lines'][0]['amount'],'200')
        wire['column_rate']=[11]
        with self.assertRaisesRegex(ValueError,'Column has no'):selection_from_wire(layout,wire)
        wire['column_rate']=[2];wire['table_id']='other'
        with self.assertRaisesRegex(ValueError,'Unknown item table'):selection_from_wire(layout,wire)

    def test_serial_numbers_cannot_be_item_description(self):
        from app.services.invoice_layout_review import ColumnMeaning,selection_from_wire
        layout,selection,_=fixture();layout.tables[0].cells[4].text='1'
        wire={k:[] for k in ColumnMeaning.model_fields}
        wire.update(document_kind='invoice',single_invoice=True,row_kinds=['header','item'],amount_basis='before_tax',sample_description=[9],sample_quantity=[10],sample_rate=[11],sample_amount=[12])
        wire.update({'header_'+k:v for k,v in selection['header'].items()})
        with self.assertRaisesRegex(ValueError,'serial/numeric'):selection_from_wire(layout,wire)

    def test_description_candidates_follow_source_columns_not_vendor(self):
        from app.services.invoice_layout_review import description_columns
        rows=[{'cells':[{'column':4,'text':'1'},{'column':2,'text':'Steel bolts'},{'column':0,'text':'12 No'},{'column':3,'text':'10.00'},{'column':1,'text':'120.00'}]}]
        self.assertEqual(description_columns(rows),[2])
        rows[0]['cells'][1]['text']='Copper wire'
        self.assertEqual(description_columns(rows),[2])

    def test_explicit_test_copy_mark_cannot_be_lost_by_model(self):
        layout,selection,_=fixture();layout.headers[0].text='Vendor A MODIFIED TEST COPY'
        raw=resolve(layout,selection)
        self.assertTrue(any('modified test copy' in issue.lower() for issue in raw['validation_issues']))
        self.assertFalse(raw['posting_allowed'])

    def test_amount_reference_rejects_labels_and_percentages(self):
        from app.services.invoice_layout_review import amount_reference_ids,source_and_rows
        layout,selection,_=fixture();source,_=source_and_rows(layout)
        self.assertIn(12,amount_reference_ids(source));self.assertNotIn(8,amount_reference_ids(source))
        selection['header']['subtotal']=[8]
        with self.assertRaisesRegex(ValueError,'value cell'):resolve(layout,selection)
        source['tokens'][12]['text']='IGST 18%'
        self.assertNotIn(12,amount_reference_ids(source))

    def test_ungrounded_selected_numeric_cell_rejected(self):
        layout,selection,_=fixture();layout.tables[0].cells[6].numeric_grounded=False
        with self.assertRaisesRegex(ValueError,'not grounded'):resolve(layout,selection)

    def test_combined_unit_never_filled_from_master(self):
        layout,selection,_=fixture();selection['lines'][0]['unit']=[]
        self.assertEqual(resolve(layout,selection)['lines'][0]['unit'],'bags')

    def test_cell_geometry_count_mismatch(self):
        _,_,res=fixture();res['table_res_list'][0]['cell_box_list'].pop()
        with self.assertRaisesRegex(ValueError,'coverage'):normalize(res,b'x',500,500,{})

    def test_cross_row_evidence_rejected(self):
        layout,selection,_=fixture();selection['lines'][0]['rate']=[7]
        with self.assertRaisesRegex(ValueError,'Cross-row'):resolve(layout,selection)

    def test_gstin_is_not_company_name(self):
        layout,selection,_=fixture();layout.headers[0].text='GSTIN: 06ABCPE1234F1ZF'
        with self.assertRaisesRegex(ValueError,'Party name'):resolve(layout,selection)

    def test_missing_row_classification(self):
        layout,selection,_=fixture();selection['rows'].pop()
        with self.assertRaisesRegex(ValueError,'classification'):resolve(layout,selection)

    def test_missing_or_duplicate_item(self):
        layout,selection,_=fixture()
        for lines in ([],selection['lines']*2):
            s=copy.deepcopy(selection);s['lines']=lines
            with self.assertRaises(ValueError):resolve(layout,s)

    def test_bad_bounds(self):
        _,_,res=fixture();res['table_res_list'][0]['cell_box_list'][0]=[-1,0,3,4]
        with self.assertRaises(ValueError):normalize(res,b'x',500,500,{})

    def test_merged_cell_grid(self):
        p=GridParser();p.feed('<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>')
        self.assertEqual(p.cells[2]['column'],1)

    def test_wrapped_description_preserved(self):
        p=GridParser();p.feed('<table><tr><td>Steel<br/>bolt</td></tr></table>')
        self.assertEqual(p.cells[0]['text'],'Steel bolt')

    def test_numeric_grounding_uses_unique_geometry_not_value_match(self):
        result={'table_res_list':[{'pred_html':'<table><tr><td>100</td></tr><tr><td>200</td></tr></table>',
            'cell_box_list':[[0,20,60,80],[0,60,60,110]]}],
            'overall_ocr_res':{'rec_texts':['100','200'],'rec_boxes':[[10,30,40,45],[10,70,40,90]]}}
        layout=normalize(result,b'x',120,120,{})
        self.assertTrue(all(c.numeric_grounded for c in layout.tables[0].cells))
        result['overall_ocr_res']['rec_texts'][1]='201'
        layout=normalize(result,b'x',120,120,{})
        self.assertFalse(layout.tables[0].cells[1].numeric_grounded)

    def test_actual_prompt_contains_contract(self):
        layout,_,_=fixture();p=payload(layout)
        self.assertIn('quantity',p['messages'][0]['content'])
        self.assertIn('table_rows',p['messages'][1]['content'])
        self.assertNotIn('tools',p)
        schema=p['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['column_rate']['items'],{'$ref':'#/$defs/ColumnIndex'})
        self.assertEqual(schema['$defs']['SourceRef']['enum'],list(range(13)))
        self.assertEqual(schema['$defs']['ColumnIndex']['enum'],[0,1,2,3])
        context=json.loads(p['messages'][1]['content'])
        self.assertEqual(context['table_rows'],[['t0',0],['t0',1]])
        rate=next(c for c in context['table_columns'] if c['column_index']==2)
        self.assertEqual([c['text'] for c in rate['cells']],['Rate','100'])
        self.assertEqual(rate['cells'][1]['source_ref'],11)


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_durable_scope_never_calls_reader_or_model(self):
        from app.services.invoice_layout_review import extract_layout_review
        from app.services.invoice_ai_budget import scope
        from fastapi import HTTPException
        token=scope.set(None)
        try:
            with patch('app.services.invoice_layout_review.httpx.AsyncClient') as reader,patch('app.ai.provider._post_json') as model:
                with self.assertRaises(HTTPException) as caught:await extract_layout_review(b'image')
                self.assertEqual(caught.exception.status_code,409)
                reader.assert_not_called();model.assert_not_called()
        finally:scope.reset(token)

    async def test_existing_generic_groq_key_used_once(self):
        from types import SimpleNamespace
        from app.services.invoice_layout_review import interpret_layout
        layout,selection,_=fixture()
        with patch('app.ai.groq_gateway.enabled',return_value=True), \
             patch('app.core.config.get_settings',return_value=SimpleNamespace(ai_api_key='existing-test-key',groq_api_key='')), \
             patch('app.ai.provider.GroqProvider',return_value=SimpleNamespace(base_url='https://example.invalid')), \
             patch('app.ai.provider._post_json',return_value={'choices':[{'message':{'content':json.dumps(selection)},'finish_reason':'stop'}],'usage':{'total_tokens':12}}) as call:
            result,telemetry=await interpret_layout(layout)
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[2],{'Authorization':'Bearer existing-test-key'})
            self.assertEqual(call.call_args.kwargs['max_attempts'],1)
            self.assertFalse(result['posting_allowed'])

    async def test_candidate_does_not_stack_old_model(self):
        from app.services.local_invoice_ocr import extract_local_photo
        with patch.dict('os.environ',{'PHILIXA_LAYOUT_REVIEW_ENABLED':'1','PHILIXA_OCR_SEMANTIC_REVIEW_ENABLED':'1'}), \
             patch('app.services.local_invoice_ocr._local_process',new_callable=AsyncMock,return_value={'tokens':[],'width':1,'height':1}), \
             patch('app.services.local_invoice_ocr.parse_tokens',side_effect=ValueError()), \
             patch('app.services.invoice_layout_review.extract_layout_review',new_callable=AsyncMock,return_value={'review':True}) as new, \
             patch('app.services.ocr_semantic_invoice.extract_review',new_callable=AsyncMock) as old:
            self.assertEqual(await extract_local_photo(b'x'),{'review':True})
            new.assert_awaited_once();old.assert_not_awaited()


if __name__=='__main__':unittest.main()
