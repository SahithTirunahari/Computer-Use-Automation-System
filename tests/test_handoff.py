"""Control transfer tests; no browser or human required."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from replay.handoff import Handoff, HandoffError
from agent.evidence import Evidence
from agent.policy import Policy, PolicyError


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.evidence = Evidence(Path(self.temp.name) / 'run')
        self.page = Mock(url='http://localhost:8000/')
        self.page.evaluate = AsyncMock()
        self.page.expose_binding = AsyncMock()
        self.page.add_init_script = AsyncMock()
        self.snapshot = patch('replay.handoff.safe_snapshot', AsyncMock(return_value={'controls': []}))
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)

    async def test_same_page_resume_and_owner(self):
        handoff = Handoff(self.page, Policy(), self.evidence, [], reader=AsyncMock(return_value='resume'))
        async def verify():
            self.assertEqual(handoff.owner, 'human')
            self.assertIs(handoff.page, self.page)
        await handoff.request('DEMO_MANUAL_LOOKUP_REQUIRED', verify)
        self.assertEqual(handoff.owner, 'automation')
        events = [json.loads(line) for line in self.evidence.path.read_text().splitlines()]
        self.assertEqual([e['owner'] for e in events if e['event'] == 'control_transferred'], ['human', 'automation'])

    async def test_wrong_state_retains_control(self):
        handoff = Handoff(self.page, Policy(), self.evidence, [], reader=AsyncMock(side_effect=['resume','resume']))
        verifier = AsyncMock(side_effect=[RuntimeError('private value'), None])
        await handoff.request('MEMBER_ID_MISMATCH', verifier)
        self.assertEqual(verifier.await_count, 2)
        self.assertIn('resume_rejected', self.evidence.path.read_text())
        self.assertNotIn('private value', self.evidence.path.read_text())

    async def test_abort_and_eof(self):
        for value in ['abort', '']:
            handoff = Handoff(self.page, Policy(), self.evidence, [], reader=AsyncMock(return_value=value))
            verify = AsyncMock()
            with self.assertRaisesRegex(HandoffError, 'HUMAN_ABORTED'):
                await handoff.request('TEST_BLOCK', verify)
            verify.assert_not_awaited()
            self.assertEqual(handoff.owner, 'stopped')

    async def test_timeout(self):
        async def reader():
            await asyncio.sleep(10)
        handoff = Handoff(self.page, Policy(), self.evidence, [], timeout=.01, reader=reader)
        with self.assertRaisesRegex(HandoffError, 'HUMAN_TIMEOUT'):
            await handoff.request('TEST_BLOCK', AsyncMock())
        self.assertEqual(handoff.owner, 'stopped')

    async def test_intervention_limit(self):
        handoff = Handoff(self.page, Policy(), self.evidence, [], max_interventions=1, reader=AsyncMock(return_value='resume'))
        await handoff.request('TEST_BLOCK', AsyncMock())
        with self.assertRaisesRegex(HandoffError, 'LIMIT'):
            await handoff.request('TEST_BLOCK', AsyncMock())

    async def test_runtime_error_cannot_resume(self):
        handoff = Handoff(self.page, Policy(), self.evidence, ['POLICY_BLOCKED_REQUEST'])
        with self.assertRaisesRegex(HandoffError, 'BLOCKED'):
            await handoff.request('TEST_BLOCK', AsyncMock())

    async def test_manual_recording_sanitizes_and_ignores_automation(self):
        handoff = Handoff(self.page, Policy(), self.evidence, [])
        await handoff.install()
        callback = self.page.expose_binding.call_args.args[1]
        data = {'event': 'input', 'control': 'secret-name', 'key': 'a', 'value': '12345'}
        await callback({'page': self.page}, data)
        self.assertFalse(self.evidence.path.exists())
        handoff.owner = 'human'
        await callback({'page': self.page}, data)
        log = self.evidence.path.read_text()
        self.assertNotIn('12345', log)
        self.assertNotIn('secret-name', log)
        self.assertEqual(json.loads(log)['control'], 'other')

    async def test_real_checkpoint_rejects_wrong_member_then_resumes(self):
        from capabilities.schema import OutcomeStep
        from replay.runner import await_outcome
        async def reader():
            self.assertEqual(handoff.owner, 'human')
            return 'resume'
        handoff = Handoff(self.page, Policy(), self.evidence, [], reader=reader)
        async def verify():
            await await_outcome(self.page, OutcomeStep(id='lookup'), '12345', Policy(), [])
        with patch('replay.runner.visible_count', AsyncMock(side_effect=[1, 0, 1, 0])), \
             patch('replay.runner.read_definition', AsyncMock(side_effect=['54321', '12345'])):
            await handoff.request('MEMBER_ID_MISMATCH', verify)
        events = [json.loads(line) for line in self.evidence.path.read_text().splitlines()]
        self.assertEqual(sum(e['event'] == 'resume_rejected' for e in events), 1)
        self.assertEqual(handoff.owner, 'automation')

    async def test_policy_failure_during_verification_stops(self):
        handoff = Handoff(self.page, Policy(), self.evidence, [], reader=AsyncMock(return_value='resume'))
        with self.assertRaises(PolicyError):
            await handoff.request('TEST_BLOCK', AsyncMock(side_effect=PolicyError('blocked')))
        self.assertEqual(handoff.owner, 'stopped')

    async def test_runtime_error_arriving_during_verification_stops(self):
        errors = []
        handoff = Handoff(self.page, Policy(), self.evidence, errors, reader=AsyncMock(return_value='resume'))
        async def verify():
            errors.append('POLICY_BLOCKED_REQUEST')
        with self.assertRaisesRegex(HandoffError, 'BLOCKED'):
            await handoff.request('TEST_BLOCK', verify)
        self.assertEqual(handoff.owner, 'stopped')
