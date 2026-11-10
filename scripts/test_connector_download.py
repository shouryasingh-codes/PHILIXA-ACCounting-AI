"""Installer preflight keeps permissions and streams the existing download URL."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from fastapi import FastAPI
from app.api.v1 import routes_tally_bridge as routes
from app.core.auth import get_current_principal


class ConnectorDownload(unittest.IsolatedAsyncioTestCase):
    async def test_head_get_and_role_permissions(self):
        app=FastAPI();app.include_router(routes.router)
        app.dependency_overrides[get_current_principal]=lambda:SimpleNamespace(role='owner')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.exe';path.write_bytes(b'MZ synthetic installer fixture')
            with patch.object(routes,'installer_path',return_value=path):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                    head=await client.head('/integrations/tally/helper/download')
                    self.assertEqual(head.status_code,200)
                    self.assertEqual(head.content,b'')
                    self.assertEqual(int(head.headers['content-length']),path.stat().st_size)
                    self.assertIn('PhilixaTallyConnectorSetup.exe',head.headers['content-disposition'])
                    get=await client.get('/integrations/tally/helper/download')
                    self.assertEqual(get.content,path.read_bytes())
                    app.dependency_overrides[get_current_principal]=lambda:SimpleNamespace(role='member')
                    self.assertEqual((await client.head('/integrations/tally/helper/download')).status_code,403)
                    self.assertEqual((await client.get('/integrations/tally/helper/download')).status_code,403)
                    app.dependency_overrides.clear()
                    self.assertEqual((await client.head('/integrations/tally/helper/download')).status_code,401)


if __name__=='__main__':unittest.main()
