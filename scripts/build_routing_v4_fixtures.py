"""Freeze replacement held-out cases after v3 contract debugging.
Consumed v3 cases are retained as regression cases, never relabelled as unseen.
"""
import copy,json
from pathlib import Path
root=Path(__file__).parent/'fixtures'/'intent_routing'
source=json.loads((root/'golden-v3.json').read_text(encoding='utf-8'))
report=json.loads((Path(__file__).parents[1]/'data'/'intent-router-golden-v3-live-heldout.json').read_text(encoding='utf-8'))
seen={r['id'] for r in report['rows']}
replacement={
'help':[
'Can you walk me through your supported abilities?',
'Is assistant ke available kaam ek baar samjhana.',
'Main naya user hoon, tumhari madad kis cheez mein le sakta hoon?',
'Which accounting activities are within your scope?',
'Ab documents ki baat nahi, mujhe product ka introduction do.',
'आपकी मदद से मैं कौन से काम कर सकता हूँ?'],
'stock':[
'Could you list the remaining inventory quantities across products?',
'Company mein bache hue sabhi goods ki quantities nikalo.',
'Inventory ka item-wise balance read karke bataogi?',
'Bilkul har item ka present quantity balance dikha do.',
'इस कंपनी के सभी सामान की उपलब्ध मात्रा दिखाइए।',
'Fetch the current stock listing, with a separate quantity for each item.'],
'document':[
'Tell me the payable total shown on the second invoice.',
'Doosra bill par jo final total likha hai woh padho.',
'Second bill ki grand total value chahiye.',
'2nd invoice mein total kitni payment likhi hai?',
'QA-102 invoice par jo bill total hai woh bataiye.',
'दूसरा बिल का कुल भुगतान कितना लिखा है?'],
'supplier':[
'Your question was about the seller: it was Sharma Traders.',
'Is maal ko bhejne wali party Gupta Traders hai.',
'For the purchase we are discussing, choose Sharma Traders.',
'Jis supplier ka naam poocha woh Gupta Traders hai.',
'Vendor details: Sharma Traders.']}
for case in source['cases']:
    if case['id'] in seen:
        case['split']='regression'
        case['consumed_in']='v3 live evaluation before document target contract repair'
new=[]
for category,messages in replacement.items():
    candidates=[c for c in source['cases'] if c['category']==category and c['id'] in seen]
    assert len(candidates)==len(messages),(category,len(candidates))
    for i,(original,message) in enumerate(zip(candidates,messages),1):
        row=copy.deepcopy(original);row.pop('consumed_in',None)
        row.update(id=f'v4-{category}-{i:02}',message=message,split='heldout')
        new.append(row)
source['cases']+=new
source['version']='meaning-routing-v4-fresh-holdout'
source['provenance']='120 development + 60 frozen untested held-out + 23 retained consumed regressions. Synthetic author labels, not real-accountant evidence.'
assert sum(c['split']=='development' for c in source['cases'])==120
assert sum(c['split']=='heldout' for c in source['cases'])==60
assert not seen.intersection(c['id'] for c in source['cases'] if c['split']=='heldout')
target=root/'golden-v4.json'
if target.exists():raise SystemExit('v4 already frozen')
target.write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen 120 development / 60 fresh held-out / 23 retained regressions')
