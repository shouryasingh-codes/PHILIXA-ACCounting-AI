"""Read-only smoke check; does not prove installed-helper or chat acceptance."""
import asyncio
import json
from app.services.tally_connector import TallyConnector, TallyError
from app.services.tally_supplier_codec import supplier_rows


async def main():
    try:
        data=await TallyConnector().catalog('Philixa Test')
        print(json.dumps({'native_read':True,'supplier_count':len(supplier_rows(data)),
            'group_count':len(data['groups']),'writes':0}))
    except TallyError:
        print(json.dumps({'native_read':False,'reason':'Tally unavailable or test company not loaded','writes':0}))

if __name__=='__main__':asyncio.run(main())
