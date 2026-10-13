"""Read only the current license mode; no serial numbers, credentials or imports."""
import asyncio
import json
from xml.etree import ElementTree as ET
from app.services.tally_connector import TallyConnector, name

XML='''<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>PhilixaLicenseRead</ID></HEADER><BODY><DESC><STATICVARIABLES><SVCURRENTCOMPANY>Philixa Test</SVCURRENTCOMPANY><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME="PhilixaLicenseRead"><TYPE>Company</TYPE><NATIVEMETHOD>Name</NATIVEMETHOD><COMPUTE>PhilixaEduMode : $$LicenseInfo:IsEducationalMode</COMPUTE><NATIVEMETHOD>PhilixaEduMode</NATIVEMETHOD><COMPUTE>PhilixaLicensedMode : $$LicenseInfo:IsLicensedMode</COMPUTE><NATIVEMETHOD>PhilixaLicensedMode</NATIVEMETHOD></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>'''

async def main():
    result=await TallyConnector().post(XML)
    selected=[r for r in result.findall('.//COMPANY') if name(r)=='Philixa Test']
    if len(selected)!=1:raise RuntimeError('Test company not uniquely loaded')
    print(json.dumps({'educational_mode':selected[0].findtext('PHILIXAEDUMODE'),
        'licensed_mode':selected[0].findtext('PHILIXALICENSEDMODE'),'accounting_writes':0}))

if __name__=='__main__':asyncio.run(main())
