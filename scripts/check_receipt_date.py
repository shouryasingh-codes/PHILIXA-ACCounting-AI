"""Read only the rejected receipt's persisted date and generated XML date."""
import asyncio,json
from xml.etree import ElementTree as ET
from app.database.session import AsyncSessionLocal
from app.models.tally import TallyAction
from app.services.tally_goods_receipt import receipt_xml

async def main():
    async with AsyncSessionLocal() as db:
        action=await db.get(TallyAction,'9883c49d353b5b8b20d1de26296acf9e')
        original=ET.fromstring(action.xml_payload)
        regenerated=ET.fromstring(receipt_xml(action.payload))
        print(json.dumps({'approved_date':action.payload['date'],'saved_xml_date':original.findtext('.//VOUCHER/DATE'),
            'current_codec_date':regenerated.findtext('.//VOUCHER/DATE'),'status':action.status,'accounting_writes':0}))
if __name__=='__main__':asyncio.run(main())
