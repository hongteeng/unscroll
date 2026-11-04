import importlib.util
import json
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unscroll.security import check_request

ROOT=Path(__file__).resolve().parents[1]


class Extension(unittest.TestCase):
    def test_unpaired_extension_cannot_read_session(self):
        r=check_request('127.0.0.1:8765','chrome-extension://example','cross-site','/api/session','','secret')
        self.assertEqual(r[0],403)

    def test_paired_extension_can_connect(self):
        for path in ('/api/session','/api/posts','/api/download'):
            self.assertIsNone(check_request('127.0.0.1:8765','chrome-extension://example','cross-site',path,'secret','secret'))

    def test_arbitrary_website_cannot_use_even_a_supplied_token(self):
        r=check_request('127.0.0.1:8765','https://evil.example','cross-site','/api/posts','secret','secret')
        self.assertEqual(r[0],403)

    def test_local_bootstrap_allowed_but_cross_site_blocked(self):
        self.assertIsNone(check_request('127.0.0.1:8765',None,'same-origin','/api/session','','secret'))
        self.assertEqual(check_request('127.0.0.1:8765',None,'cross-site','/api/session','','secret')[0],403)
        self.assertEqual(check_request('127.0.0.1:8765',None,None,'/api/posts','','secret')[0],401)
        self.assertEqual(check_request('evil.example',None,None,'/api/session','','secret')[0],403)

    def test_no_empty_token_authentication(self):
        self.assertEqual(check_request('127.0.0.1:8765','chrome-extension://example',None,'/api/session','','')[0],403)

    def test_packaged_assets_match_canonical_ui(self):
        for name in ('app.js','style.css'):
            self.assertEqual((ROOT/'extension'/name).read_bytes(),(ROOT/'unscroll'/'static'/name).read_bytes())
        html=(ROOT/'extension'/'library.html').read_text()
        self.assertNotIn('/static/',html)
        self.assertIn('href="library.html"',html)
        self.assertIn('id="connect-dialog"',html)
        self.assertIn('id="pairing-token"',html)

    def test_manifest_is_local_only_and_contains_library(self):
        manifest=json.loads((ROOT/'extension'/'manifest.json').read_text())
        self.assertEqual(manifest['host_permissions'],['http://127.0.0.1/*'])
        self.assertIn("script-src 'self'",manifest['content_security_policy']['extension_pages'])
        self.assertNotIn('unsafe-eval',manifest['content_security_policy']['extension_pages'])
        self.assertIn('chrome.runtime.getURL(\'library.html\')',(ROOT/'extension'/'popup.js').read_text())
        for path in ('popup.html','popup.js','popup.css','library.html','app.js','style.css'):
            self.assertTrue((ROOT/'extension'/path).is_file())

    def test_launch_agent_uses_venv_and_loopback(self):
        spec=importlib.util.spec_from_file_location('helper_service',ROOT/'helper_service.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        root=Path('/Users/Owner/Applications/Unscroll')
        config=module.service_spec(root,root/'.venv/bin/python',Path('/tmp/unscroll-logs'))
        self.assertEqual(config['ProgramArguments'][0],str(root/'.venv/bin/python'))
        self.assertIn('127.0.0.1',config['ProgramArguments'])
        self.assertTrue(config['RunAtLoad'])
        self.assertEqual(config['WorkingDirectory'],str(root))


if __name__=='__main__':unittest.main()
