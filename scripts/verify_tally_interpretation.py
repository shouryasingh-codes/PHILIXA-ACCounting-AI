"""Provider interpretation of synthetic commands only; no Tally writes or messages."""
import asyncio
from decimal import Decimal
from app.api.v1.routes_business import CommandRequest,interpret


async def main():
    masters={'items':['Cement'],'parties':['Sharma Traders','Rahul Traders'],'units':['bags'],'companies':['Sharma Traders','Philixa Test']}
    cases=[
        ('Sharma Traders se 10 Cement bags 350 rupees per bag kharide, entry karo.','purchase_create',Decimal('10'),Decimal('350')),
        ('Rahul Traders ko 2 Cement bags 400 rupees per bag beche, entry karo.','sale_create',Decimal('2'),Decimal('400')),
        ('सीमेंट का स्टॉक कितना है?','stock_read',None,None),
    ]
    for text,intent,qty,rate in cases:
        parsed=await interpret(CommandRequest(text=text),[],masters)
        assert parsed.intent==intent and parsed.item_name=='Cement',parsed.model_dump()
        if qty:
            assert parsed.quantity==qty and parsed.rate==rate and parsed.unit=='bags',parsed.model_dump()
        print('PASS: synthetic Hindi/Hinglish command -> '+intent)
    parsed=await interpret(CommandRequest(text='Sharma Traders se 2 Cement bags 350 per bag GST ke saath kharide, entry karo.'),[],masters)
    assert parsed.unsupported_reason or parsed.intent=='general',parsed.model_dump()
    print('PASS: GST command is not silently reduced to a non-GST voucher')
    for query,company in [('Sharma Traders mein Cement ka stock?', 'Sharma Traders'),('Sab companies mein Cement stock?',None),('Cement ka stock kitna hai?',None)]:
        parsed=await interpret(CommandRequest(text=query),[],masters)
        assert parsed.intent=='stock_read' and parsed.item_name=='Cement' and parsed.company_query==company,parsed.model_dump()
        print('PASS: named/all/omitted company scope')


if __name__=='__main__':
    asyncio.run(main())
