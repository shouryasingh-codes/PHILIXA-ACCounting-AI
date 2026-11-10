"""Preserve v1 failures. Replace the eight consumed held-out turns before v2 evaluation."""
import json
from pathlib import Path

root=Path(__file__).parent/'fixtures'/'intent_routing'
source=json.loads((root/'golden-v1.json').read_text(encoding='utf-8'))
replacements={
    'help':'Could you introduce what this assistant is useful for?',
    'stock_all':'Show quantities on hand for the full inventory list',
    'stock_item':'Paint ki kitni quantity filhaal available hai?',
    'purchase':'Metro se Paint ke 8 cans 225 rate par liye hain',
    'supplier_reply':'Abhi wale supplier question ka jawab Metro Traders hai',
    'correction':'Price correction for this draft: 210 per can, not 225',
    'topic_switch':'Draft saved rehne do; mujhe inventory quantities padhni hain',
    'compound':'Read the uploaded invoice and list inventory quantities too'}
used=[]
for case in source['cases']:
    if case['split']=='heldout' and case['id'].endswith('-0') and case['category'] in replacements:
        used.append(dict(case));case['message']=replacements[case['category']];case['id']+='-v2'
source.update(version='routing-golden-v2',consumed_v1_regressions=used,
    lineage='Eight v1 evaluation turns are regression-only. Seventy-two unrun v1 turns and eight new turns form the frozen v2 held-out set. No v1 failure is erased.')
target=root/'golden-v2.json'
if target.exists():raise SystemExit('Frozen v2 dataset already exists.')
target.write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen v2: 160 development, 80 held-out, 8 separate consumed-v1 regressions.')
