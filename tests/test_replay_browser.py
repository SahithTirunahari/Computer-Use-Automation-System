"""Opt-in real replay integration: no model calls or scripted decisions."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from capabilities.schema import Capability
from agent.evidence import Evidence
from agent.policy import Policy
from replay.runner import run_replay

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('RUN_BROWSER_TESTS') == '1', 'Requires a running portal and browser')
class ReplayBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_inputs_same_artifact(self):
        local = ROOT / '.venv/playwright-browsers'
        if local.is_dir():
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(local))
        capability = Capability.model_validate_json((ROOT / 'capabilities/get_savings_balance.v1.json').read_text())
        for member_id, balance in [('12345', '$4,231.12'), ('54321', '$850.50'), ('99999', None)]:
            with self.subTest(member_id=member_id), tempfile.TemporaryDirectory() as folder:
                evidence = Evidence(Path(folder) / 'run')
                args = SimpleNamespace(member_id=member_id, url='http://localhost:8000', timeout=30, headed=False, slow_mo=0)
                result = await run_replay(args, capability, Policy(), evidence)
                if balance:
                    self.assertEqual(result.status, 'success', result.code)
                    self.assertEqual(result.outputs, {'member_id': member_id, 'savings_balance': balance})
                else:
                    self.assertEqual(result.status, 'business_outcome', result.code)
                    self.assertEqual(result.code, 'MEMBER_NOT_FOUND')
                evidence.finish(result)
                self.assertNotIn(member_id, evidence.path.read_text())
