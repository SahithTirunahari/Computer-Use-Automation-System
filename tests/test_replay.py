"""Replay tests use controlled browser doubles; no provider or live model."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from capabilities.schema import Capability
from agent.evidence import Evidence
from agent.policy import Policy
from replay.runner import (validate_input, bind_action, await_outcome, verify_success,
                           execute_flow, run_replay, ReplayError)

ROOT = Path(__file__).resolve().parents[1]


def locator(count=0):
    loc = Mock()
    loc.count = AsyncMock(return_value=count)
    loc.nth.return_value.is_visible = AsyncMock(return_value=True)
    return loc


def page_for(details=0, missing=0, alert=0, member_id='12345'):
    page = Mock(url=f'http://localhost:8000/member?member_id={member_id}')
    page.get_by_role.side_effect = lambda role, **kw: locator(
        alert if role == 'alert' else details if kw.get('name') == 'Member Details' else missing)
    page.get_by_text.return_value = locator(1)
    return page


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cap = Capability.model_validate_json((ROOT / 'capabilities/get_savings_balance.v1.json').read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.evidence = Evidence(Path(self.temp.name) / 'run')

    def test_input_and_binding(self):
        for value in ('', 'abc', '1234', '123456', ' 12345', 12345):
            with self.assertRaises(ReplayError):
                validate_input(self.cap, value)
        validate_input(self.cap, '00001')
        self.assertEqual(bind_action(self.cap.steps[0], '54321').value, '54321')
        self.assertEqual(self.cap.steps[0].value.input, 'member_id')

    def test_no_model_imports(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import replay.runner; assert not any(n in sys.modules for n in ['openai','httpx','agent.decision','agent.ollama'])"],
            cwd=ROOT, check=True)

    async def test_details_and_not_found(self):
        with patch('replay.runner.read_definition', AsyncMock(return_value='12345')):
            result = await await_outcome(page_for(details=1), self.cap.steps[2], '12345', Policy(), [])
            self.assertEqual(result, 'DETAILS_VERIFIED')
        result = await await_outcome(page_for(missing=1, member_id='99999'), self.cap.steps[2], '99999', Policy(), [])
        self.assertEqual(result, 'MEMBER_NOT_FOUND')

    async def test_ambiguous_wrong_identity_validation_and_timeout(self):
        cases = [(page_for(details=1, missing=1), 'AMBIGUOUS_OUTCOME'),
                 (page_for(details=2), 'AMBIGUOUS_OUTCOME'),
                 (page_for(alert=1), 'APPLICATION_VALIDATION_ERROR'),
                 (page_for(missing=1), 'BUSINESS_OUTCOME_NOT_VERIFIED'),
                 (page_for(), 'UNEXPECTED_STATE_OR_TIMEOUT')]
        checkpoint = self.cap.steps[2].model_copy(update={'timeout_ms': 1})
        for page, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(ReplayError, code):
                await await_outcome(page, checkpoint, '99999', Policy(), [])
        with patch('replay.runner.read_definition', AsyncMock(return_value='54321')):
            with self.assertRaisesRegex(ReplayError, 'MEMBER_ID_MISMATCH'):
                await await_outcome(page_for(details=1), checkpoint, '12345', Policy(), [])

    async def test_delayed_outcome(self):
        page = page_for()
        sequence = iter([0, 0, 0, 1, 0])
        with patch('replay.runner.visible_count', AsyncMock(side_effect=lambda _: next(sequence))), \
             patch('replay.runner.read_definition', AsyncMock(return_value='12345')):
            result = await await_outcome(page, self.cap.steps[2], '12345', Policy(), [])
        self.assertEqual(result, 'DETAILS_VERIFIED')

    async def test_outputs_verified_and_stale_rejected(self):
        outputs = {'member_id': '12345', 'savings_balance': '$4,231.12'}
        for values, expected_error in [(['12345', '$4,231.12'], None), (['12345', '$1.00'], 'STALE_OUTPUT')]:
            with patch('replay.runner.read_definition', AsyncMock(side_effect=values)):
                if expected_error:
                    with self.assertRaisesRegex(ReplayError, expected_error):
                        await verify_success(page_for(details=1), self.cap, outputs, '12345')
                else:
                    await verify_success(page_for(details=1), self.cap, outputs, '12345')
        with self.assertRaisesRegex(ReplayError, 'OUTPUTS_MISSING'):
            await verify_success(page_for(details=1), self.cap, {}, '12345')

    async def test_flow_uses_artifact_and_redacts(self):
        seen = []
        async def act(page, action, outputs):
            seen.append(action.action)
            if action.action == 'extract':
                outputs[action.output_name] = {'member_id': '54321', 'savings_balance': '$850.50'}[action.output_name]
        with patch('replay.runner.safe_snapshot', AsyncMock(return_value={})), \
             patch('replay.runner.execute_action', act), \
             patch('replay.runner.await_outcome', AsyncMock(return_value='DETAILS_VERIFIED')), \
             patch('replay.runner.verify_success', AsyncMock()):
            result = await execute_flow(page_for(member_id='54321'), self.cap, '54321', Policy(), self.evidence, [])
        self.assertEqual(seen, ['type', 'keypress', 'extract', 'extract'])
        self.assertEqual(result.outputs['savings_balance'], '$850.50')
        self.evidence.finish(result)
        log = self.evidence.path.read_text()
        self.assertNotIn('54321', log)
        self.assertNotIn('$850.50', log)

    async def test_not_found_skips_extraction(self):
        act = AsyncMock()
        with patch('replay.runner.safe_snapshot', AsyncMock(return_value={})), \
             patch('replay.runner.execute_action', act), \
             patch('replay.runner.await_outcome', AsyncMock(return_value='MEMBER_NOT_FOUND')):
            result = await execute_flow(page_for(member_id='99999'), self.cap, '99999', Policy(), self.evidence, [])
        self.assertEqual(act.await_count, 2)
        self.assertEqual(result.status, 'business_outcome')
        self.assertEqual(result.outputs, {})

    async def test_invalid_input_never_launches_browser(self):
        args = SimpleNamespace(member_id='abc')
        with patch('replay.runner.async_playwright') as launch:
            result = await run_replay(args, self.cap, Policy(), self.evidence)
        launch.assert_not_called()
        self.assertEqual(result.code, 'INVALID_INPUT')

    async def test_total_timeout_and_cleanup(self):
        args = SimpleNamespace(member_id='12345', url='http://localhost:8000', timeout=.01, headed=False, slow_mo=0)
        browser = AsyncMock()
        page = Mock()
        page.goto = AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(1))
        # An actual async coroutine keeps navigation pending until cancellation.
        async def slow(*a, **kw):
            await asyncio.sleep(1)
        page.goto = slow
        browser.new_context.return_value.new_page.return_value = page
        manager = AsyncMock()
        manager.__aenter__.return_value.chromium.launch.return_value = browser
        with patch('replay.runner.async_playwright', return_value=manager):
            result = await run_replay(args, self.cap, Policy(), self.evidence)
        self.assertEqual(result.code, 'OVERALL_TIMEOUT')
        browser.close.assert_awaited_once()

    async def test_forbidden_origin_rejected_before_browser_launch(self):
        args = SimpleNamespace(member_id='12345', url='http://example.com')
        with patch('replay.runner.async_playwright') as launch:
            result = await run_replay(args, self.cap, Policy(), self.evidence)
        launch.assert_not_called()
        self.assertEqual(result.code, 'POLICY_BLOCKED')

    async def test_request_guard_blocks_before_dispatch(self):
        for url, method in [('http://example.com/data', 'GET'),
                            ('http://localhost:8000/member', 'POST')]:
            with self.subTest(url=url, method=method):
                browser = AsyncMock()
                context = browser.new_context.return_value
                page = Mock(url='http://localhost:8000/')
                context.new_page.return_value = page
                callbacks = []
                async def install_route(pattern, callback):
                    callbacks.append(callback)
                context.route.side_effect = install_route
                route = SimpleNamespace(request=SimpleNamespace(url=url, method=method),
                                        abort=AsyncMock(), continue_=AsyncMock())
                async def navigate(*args, **kwargs):
                    await callbacks[0](route)
                    return SimpleNamespace(ok=True)
                page.goto = navigate
                manager = AsyncMock()
                manager.__aenter__.return_value.chromium.launch.return_value = browser
                args = SimpleNamespace(member_id='12345', url='http://localhost:8000',
                                       timeout=10, headed=False, slow_mo=0)
                with patch('replay.runner.async_playwright', return_value=manager), \
                     patch('replay.runner.safe_snapshot', AsyncMock(return_value={})):
                    result = await run_replay(args, self.cap, Policy(), self.evidence)
                route.abort.assert_awaited_once()
                route.continue_.assert_not_awaited()
                browser.close.assert_awaited_once()
                self.assertEqual(result.code, 'POLICY_BLOCKED_REQUEST')
