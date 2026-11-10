"""Development-only shape diagnostics through the normal evaluator/gateway.
No documents, prompts, credentials, quote values or arbitrary provider bodies logged.
"""
import argparse,asyncio,json
from pathlib import Path
from app.services import intent_router_model as model
from scripts import evaluate_intent_routing as evaluation

async def main():
    cases=json.loads(evaluation.DATA.read_text(encoding='utf-8'))['cases']
    case=next(c for c in cases if c['id']=='v3-supplier-05' and c['split']=='development')
    original=model._post_json
    def observed(*args,**kwargs):
        result=original(*args,**kwargs)
        try:
            value=json.loads(result['choices'][0]['message']['content'])
            print(json.dumps({'synthetic_development_shape':{
                'intent':value.get('intent'),'relation':value.get('context_relation'),
                'target_draft_supplied':bool(value.get('document_draft_id')),
                'document_fields':value.get('document_fields'),
                'item_filter_supplied':bool(value.get('item_name')),
                'update_paths':[u.get('path') for u in value.get('explicit_fields',[])],
                'report_supplied':bool(value.get('report')),'date_count':len(value.get('report_dates',[]))}}),flush=True)
        except (KeyError,ValueError,TypeError):pass
        return result
    model._post_json=observed
    try:await evaluation.main(argparse.Namespace(dataset=None,live=True,resume=False,max_calls=1,split='development',case_id=case['id']))
    finally:model._post_json=original

if __name__=='__main__':asyncio.run(main())
