import unittest
from xml.etree.ElementTree import Element, SubElement
from app.services.tally_supplier_codec import supplier_rows
from app.services.tally_sync_protocol import serialize_catalog, deserialize_catalog


def row(tag, title, parent):
    r=Element(tag,NAME=title);SubElement(r,'PARENT').text=parent;return r


class Classification(unittest.TestCase):
    def test_nested_supplier_customer_and_cycle(self):
        catalog={'ledgers':[row('LEDGER','Supplier','Local'),row('LEDGER','Customer','Sundry Debtors'),row('LEDGER','Cycle ledger','Cycle')],
            'groups':[row('GROUP','Local','Region'),row('GROUP','Region','Sundry Creditors'),row('GROUP','Cycle','Cycle')]}
        self.assertEqual([r.get('NAME') for r in supplier_rows(catalog)],['Supplier'])

    def test_unknown_group_does_not_become_supplier(self):
        self.assertEqual(supplier_rows({'ledgers':[row('LEDGER','Unknown','Missing')]}),[])

    def test_group_snapshot_roundtrip_and_old_compatibility(self):
        catalog={'non_gst':True,'cost_centres_enabled':False,'items':[],'units':[],'godowns':[],'ledgers':[],
            'groups':[row('GROUP','Local','Sundry Creditors')]}
        data=serialize_catalog(catalog)
        self.assertEqual(deserialize_catalog(data)['groups'][0].get('NAME'),'Local')
        del data['groups'];self.assertEqual(deserialize_catalog(data)['groups'],[])

    def test_malformed_group_snapshot_rejected(self):
        from app.services.tally_connector import TallyError
        catalog={'non_gst':True,'cost_centres_enabled':False,'items':[],'units':[],'godowns':[],'ledgers':[], 'groups':['<LEDGER NAME="Fake"/>']}
        with self.assertRaises(TallyError):deserialize_catalog(catalog)

if __name__=='__main__':unittest.main()
