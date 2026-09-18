"""Opt-in live-browser adapter check with SCRIPTED decisions, never LLM evidence.
Run the portal first, then RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v.
"""
import os
from pathlib import Path
import tempfile
import time
import unittest
from playwright.async_api import async_playwright
from agent.actions import Decision
from agent.agent import discovery_loop
from agent.evidence import Evidence
from agent.policy import Policy


class ScriptedDecider:
    last_metadata = {'test_only': True}

    def __init__(self, member_id):
        raw = [
            {'action': 'type', 'target': {'kind': 'role', 'role': 'textbox', 'name': 'Member ID'}, 'value': member_id},
            {'action': 'click', 'target': {'kind': 'role', 'role': 'button', 'name': 'Search'}},
        ]
        if member_id == '99999':
            raw += [{'action': 'done', 'result': {'status': 'business_outcome', 'code': 'MEMBER_NOT_FOUND'}}]
        else:
            raw += [
                {'action': 'extract', 'target': {'kind': 'definition', 'label': 'Member ID'}, 'output_name': 'member_id'},
                {'action': 'extract', 'target': {'kind': 'definition', 'label': 'Current Savings Balance'}, 'output_name': 'savings_balance'},
                {'action': 'done', 'result': {'status': 'success', 'output_keys': ['member_id', 'savings_balance']}},
            ]
        self.actions = iter(raw)

    async def decide(self, *args):
        return Decision.model_validate({'next_action': {'reason': 'Scripted adapter test', **next(self.actions)}})


@unittest.skipUnless(os.getenv('RUN_BROWSER_TESTS') == '1', 'Opt-in: requires a browser and running portal')
class BrowserIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_and_business_outcome(self):
        local = Path(__file__).resolve().parents[1] / '.venv' / 'playwright-browsers'
        if local.is_dir():
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(local))
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                for member_id, balance in [('12345', '$4,231.12'), ('54321', '$850.50'), ('99999', None)]:
                    context = await browser.new_context()
                    try:
                        page = await context.new_page()
                        await page.goto('http://localhost:8000/')
                        with tempfile.TemporaryDirectory() as folder:
                            evidence = Evidence(Path(folder) / 'test-run')
                            result = await discovery_loop(page, ScriptedDecider(member_id),
                                f'Find current savings balance for member {member_id}.', Policy(), evidence, 10,
                                time.monotonic() + 30, [])
                            if balance:
                                self.assertEqual(result.status, 'success')
                                self.assertEqual(result.outputs['savings_balance'], balance)
                            else:
                                self.assertEqual(result.code, 'MEMBER_NOT_FOUND')
                            logs = evidence.path.read_text()
                            self.assertNotIn(member_id, logs)
                            if balance:
                                self.assertNotIn(balance, logs)
                    finally:
                        await context.close()
            finally:
                await browser.close()
