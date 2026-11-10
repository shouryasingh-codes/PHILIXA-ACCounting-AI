"""Process-boundary recovery against a synthetic Tally transport; no HTTP writes."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, patch


async def child(folder, mode):
    from scripts.test_gst_purchase import catalog, content, profile, config
    from app.services import tally_gst_purchase as gst
    from app.services.tally_connector import parse_xml, tag, TallyError
    root = Path(folder)
    payload = json.loads((root / 'payload.json').read_text())
    async def collection(*args):
        path = root / 'voucher.xml'
        return [parse_xml(path.read_bytes())] if path.exists() else []
    async def post(xml):
        with (root / 'imports.txt').open('a') as stream:
            stream.write('import\n')
        if mode == 'timeout':
            raise TallyError('synthetic connection lost before acknowledgement')
        voucher = parse_xml(xml.encode()).find('.//VOUCHER')
        tag(voucher, 'VOUCHERNUMBER', 'RECOVERY-1')
        from xml.etree.ElementTree import tostring
        (root / 'voucher.xml').write_bytes(tostring(voucher))
        if mode == 'crash':
            os._exit(73)  # Simulate helper death after Tally accepted the import.
    connector = SimpleNamespace(catalog=AsyncMock(return_value=catalog()), collection=collection, post=post)
    with patch.dict(os.environ, {'PHILIXA_GST_PURCHASE_ACCEPTANCE_ENABLED': '1'}):
        result = await gst.execute('purchase_gst_post', connector, 'Pilot Test', 'identity', payload, config(), root / 'journal.sqlite3')
    print(json.dumps(result))


class ProcessRecovery(unittest.TestCase):
    def run_child(self, folder, mode):
        result = subprocess.run([sys.executable, '-m', 'scripts.test_day10_recovery', '--child', folder, mode],
                                capture_output=True, text=True, timeout=45,
                                env={**os.environ, 'LITELLM_LOCAL_MODEL_COST_MAP': 'True'})
        return result

    def prepare(self, folder):
        from scripts.test_gst_purchase import catalog, content, profile, config
        from app.services import tally_gst_purchase as gst
        payload = gst.compile_purchase(catalog(), content(), profile(), config(), str(uuid.uuid4()))
        (Path(folder) / 'payload.json').write_text(json.dumps(payload))
        return payload

    def test_process_death_after_import_reconciles_same_action(self):
        with tempfile.TemporaryDirectory() as folder:
            original = self.prepare(folder)
            self.assertEqual(self.run_child(folder, 'crash').returncode, 73)
            for _ in range(2):
                result = self.run_child(folder, 'normal')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'verified')
            self.assertEqual((Path(folder) / 'imports.txt').read_text().splitlines(), ['import'])
            self.assertEqual(json.loads((Path(folder) / 'payload.json').read_text())['date'], original['date'])

    def test_timeout_without_visible_voucher_never_resends_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            self.prepare(folder)
            for mode in ('timeout', 'normal', 'normal'):
                result = self.run_child(folder, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'], 'verification_pending')
            self.assertEqual((Path(folder) / 'imports.txt').read_text().splitlines(), ['import'])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        asyncio.run(child(sys.argv[2], sys.argv[3]))
    else:
        unittest.main()
