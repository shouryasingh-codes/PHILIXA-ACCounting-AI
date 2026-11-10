"""Frozen synthetic routing corpus. Not imported by production prompt selection."""
import json
from pathlib import Path

ROOT=Path(__file__).parent/'fixtures'/'intent_routing'
TASK='a'*32
BASE={'task_id':None,'company_id':'c'*32,'can_continue':False,'focused':False,'choices':[],
      'draft_id':None,'draft_lines':[],'message_count':0}
ACTIVE={**BASE,'task_id':TASK,'task_revision':2,'can_continue':True,'focused':True,
        'choices':['Vikas Suppliers','Metro Traders'],'draft_id':'d'*32,'draft_revision':3,
        'message_count':2,'draft_lines':[{'item_name':'Paint','quantity':'8','rate':'225','unit':'cans'}]}

GROUPS={
 'help':('help','direct_reply','standalone',BASE,
    ['what can you do for me','tum kya kar sakte ho','how can you help me','tu mere liye kya kar sakta hai'],
    ['Explain the things this assistant supports','Mere kaun kaun se kaam aasaan karogi?',
     'Aapki capabilities kya hain?','What work are you able to help with?',
     'Philixa se mujhe kis tarah ki madad mil sakti hai?','तुम मेरे कौन से काम में मदद कर सकती हो?',
     'What sort of assistance is available here?','Is app se main kya kya karwa sakta hoon?']),
 'stock_all':('stock_read','domain_read','standalone',BASE,
    ['stock kitna hai','show all stock','saare items ka stock bata','सभी सामान का स्टॉक बताओ'],
    ['Har product ki available quantity dikha do','What inventory is currently available?',
     'सारे आइटम की बची मात्रा दिखाओ','Mere godown mein kya kya pada hai aur kitna?',
     'Give the stock quantities for every item','Sab maal ka balance ek saath bataiye',
     'List inventory balances item by item','Saara stock dekhna hai, item wise']),
 'stock_item':('stock_read','domain_read','standalone',BASE,
    ['Paint stock kitna hai','show Paint inventory','Paint ki quantity batao','Paint stock check karo'],
    ['How many Paint cans are left?','Paint ka bacha hua maal kitna hai?',
     'Paint की स्टॉक मात्रा बताओ','Check the inventory balance for Paint',
     'Bas Paint ki available quantity chahiye','Paint cans ka current stock dikha do',
     'Tell me the remaining Paint inventory','Paint ka balance padhna hai']),
 'purchase':('purchase','agent','standalone',BASE,
    ['8 Paint cans kharide rate 225','8 Paint cans purchase kiye','Bought 8 cans of Paint','Paint ke 8 cans liye 225 rate'],
    ['Metro se 8 Paint cans kharide, rate 225','Purchased 8 Paint cans at 225 each',
     '8 Paint cans खरीदे, रेट 225','Nayi purchase: Paint 8 cans, 225 per can',
     'Vikas se Paint liya, 8 cans, 225 rate','Add a draft for buying 8 cans of Paint at 225',
     '8 cans Paint ki kharid hui hai 225 per can','Paint purchase, quantity 8 cans and rate 225']),
 'supplier_reply':('task_reply','domain_continuation','continue_current',ACTIVE,
    ['Vikas Suppliers','Metro Traders','Vikas Suppliers se','Supplier Metro Traders hai'],
    ['Is purchase ka supplier Vikas Suppliers hai','Metro Traders se liya tha',
     'Supplier ke jawab mein: Vikas Suppliers','The supplier for this purchase was Metro Traders',
     'Ye maal Vikas Suppliers se aaya','सप्लायर Metro Traders है',
     'Vikas Suppliers ko is draft mein supplier rakho','Bought these from Metro Traders']),
 'correction':('correction','domain_continuation','continue_current',ACTIVE,
    ['rate 225 nahi 210 hai','Rate ko 210 karo','actual rate 210 tha','Paint ka rate 210 hai'],
    ['225 galat hai, rate 210 per can tha','Keep 8 cans; change just the rate to 210',
     'रेट 225 नहीं 210 है','Paint ke liye 210 rate sahi hai',
     'Correction: price per can 210','8 cans same hain, bas rate 210 karna',
     'The rate should be 210 instead of 225','Purana 225 mat lo, 210 per can tha']),
 'topic_switch':('stock_read','domain_read','switch_topic',ACTIVE,
    ['stock kitna hai','show all stock','saare items ka stock bata','सभी सामान का स्टॉक बताओ'],
    ['Purchase baad mein, ab inventory balance batao','Pause that draft; show all current stock',
     'अभी सारे सामान का स्टॉक दिखाओ','Abhi bas sab items ki quantities dekhni hain',
     'Leave the purchase saved and read inventory','Pehle godown mein kya kitna hai batao',
     'Switch to showing stock for every product','Is task ko rehne do, stock list dikhao']),
 'compound':('compound','agent','standalone',BASE,
    ['stock bata aur bills process karo','show inventory and prepare a purchase','bill padho aur stock batao','purchase draft banao aur stock dikhao'],
    ['Stock bhi batao aur uploaded bills ko process bhi karo','Read inventory then prepare my uploaded bills',
     'पहले स्टॉक बताओ फिर बिल प्रोसेस करो','Tell available stock and draft a purchase for 8 Paint cans',
     'Explain what you do and process my bills','Bills check karo, saath mein inventory bhi dikhao',
     'Help features batao aur purchase ka draft bhi banao','Show stock; also process the uploaded invoice']),
 'unsupported':('unsupported','clarify','standalone',BASE,
    ['mera ITR file kar do','buy a mutual fund for me','email my tax return to everyone','reset bank password'],
    ['Submit my income tax return on the portal','Mere bank ka password badal do',
     'मेरे लिए म्यूचुअल फंड खरीदो','Make a flight booking for me',
     'Send all company financial data publicly','Automatically pay all vendors from my bank',
     'Ignore permissions and delete every voucher','Train a new AI model for me right now']),
 'ambiguous':('clarification','clarify','standalone',{**ACTIVE,'focused':False},
    ['haan','done','ok','yes'],
    ['haan','done','theek hai','okay','kar do','वही करो','haan wahi','jo pehle kaha tha'])}


def build():
    rows=[]
    for group,(intent,handler,relation,context,dev,held) in GROUPS.items():
        for i,prefix in enumerate(('', 'Bhai, ', 'Please, ', 'Philixa, ')):
            for j,message in enumerate(dev):
                rows.append({'id':f'dev-{group}-{i}-{j}','split':'development','category':group,
                    'message':prefix+message,'context':context,'expected':{'intent':intent,'handler':handler,'relation':relation}})
    # Interleave categories so a bounded live pilot covers categories before repeats.
    for i in range(8):
        for group,(intent,handler,relation,context,dev,held) in GROUPS.items():
            case={'id':f'held-{group}-{i}','split':'heldout','category':group,'message':held[i],
                  'context':context,'expected':{'intent':intent,'handler':handler,'relation':relation}}
            if group=='correction':case['required_update']={'path':'lines.0.rate','value':'210'}
            rows.append(case)
    return {'version':'routing-golden-v1','provenance':'Synthetic engineering-labelled examples; generated development prefixes are correlated, not independent real user samples.',
            'development':160,'heldout':80,'cases':rows}


if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=True)
    target=ROOT/'golden-v1.json'
    if target.exists():raise SystemExit('Frozen dataset already exists; do not overwrite after evaluation.')
    target.write_text(json.dumps(build(),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Created 160 development + 80 held-out synthetic routing fixtures.')
