"""Offline tests. Scripted decisions here are NOT live discovery evidence."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from agent.actions import Decision
from agent.agent import discovery_loop, requested_member
from agent.evidence import Evidence, safe_action
from agent.executor import ActionError, execute_action, verify_done, unique_visible
from agent.observer import Observation
from agent.policy import Policy, PolicyError


def decision(action, **kwargs):
    return Decision.model_validate({'next_action': {'action': action, 'reason': 'Operate lookup', **kwargs}})


def done():
    return decision('done', result={'status': 'success', 'output_keys': ['member_id', 'savings_balance']}).next_action


def visible(text=''):
    return SimpleNamespace(count=AsyncMock(return_value=1), is_visible=AsyncMock(return_value=True),
                           inner_text=AsyncMock(return_value=text))


class SchemaPolicyTests(unittest.TestCase):
    def test_type_requires_value(self):
        with self.assertRaises(ValidationError):
            decision('type', target={'kind': 'role', 'role': 'textbox', 'name': 'Member ID'})

    def test_code_and_selectors_rejected(self):
        for payload in [dict(action='evaluate', code='alert(1)'),
                        dict(action='click', target={'kind': 'xpath', 'selector': '//button'})]:
            with self.assertRaises(ValidationError):
                Decision.model_validate({'next_action': {'reason': 'x', **payload}})

    def test_final_value_cannot_be_invented(self):
        with self.assertRaises(ValidationError):
            decision('done', result={'status': 'success', 'output_keys': ['member_id', 'savings_balance'],
                                     'outputs': {'savings_balance': '$100'}})

    def test_wait_requires_condition(self):
        with self.assertRaises(ValidationError):
            decision('wait', target={'kind': 'role', 'role': 'button', 'name': 'Search'})

    def test_url_allowlist(self):
        for url in ['https://evil.example/', 'http://localhost:8000/admin',
                    'http://localhost:8000/?token=secret', 'http://localhost:8000.evil.example/',
                    'http://user:pass@localhost:8000/', 'http://localhost:8000/member?member_id=1&member_id=2']:
            with self.subTest(url=url), self.assertRaises(PolicyError):
                Policy().check_url(url)
        Policy().check_url('http://localhost:8000/member?member_id=12345')

    def test_policy_rejects_wrong_parameter_and_risky_button(self):
        for action in [decision('type', target={'kind': 'role', 'role': 'textbox', 'name': 'Member ID'}, value='54321'),
                       decision('click', target={'kind': 'role', 'role': 'button', 'name': 'Transfer funds'})]:
            with self.assertRaises(PolicyError):
                Policy().check_action(action.next_action, '12345')

    def test_mislabeled_extraction_blocked(self):
        action = decision('extract', target={'kind': 'definition', 'label': 'Member Name'}, output_name='savings_balance')
        with self.assertRaises(PolicyError):
            Policy().check_action(action.next_action, '12345')

    def test_goal_scope(self):
        self.assertEqual(requested_member('Find savings balance for member 12345.'), '12345')
        for goal in ['Transfer money to 12345', 'Savings balance for 12345 and 54321', 'Savings balance for 123456']:
            with self.assertRaises(ValueError):
                requested_member(goal)

    def test_logs_omit_values_and_free_text(self):
        action = decision('type', target={'kind': 'role', 'role': 'textbox', 'name': 'secret-name'}, value='12345').next_action
        action.reason = 'secret-token Alice Johnson $4,231.12'
        rendered = json.dumps(safe_action(action))
        for secret in ['secret-name', 'secret-token', 'Alice Johnson', '$4,231.12', '12345']:
            self.assertNotIn(secret, rendered)

    def test_sdk_schema_is_strict(self):
        from openai.lib._pydantic import to_strict_json_schema
        schema = to_strict_json_schema(Decision)
        self.assertEqual(schema['type'], 'object')
        for definition in schema['$defs'].values():
            if definition.get('type') == 'object':
                self.assertFalse(definition['additionalProperties'])
                self.assertEqual(set(definition['required']), set(definition['properties']))


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_extract_reads_page(self):
        action = decision('extract', target={'kind': 'definition', 'label': 'Current Savings Balance'}, output_name='savings_balance').next_action
        outputs = {}
        with patch('agent.executor.unique_visible', AsyncMock(return_value=visible('$4,231.12'))):
            await execute_action(Mock(), action, outputs)
        self.assertEqual(outputs, {'savings_balance': '$4,231.12'})

    async def test_ambiguous_target_fails(self):
        locator = visible()
        locator.count.return_value = 2
        with patch('agent.executor.resolve', return_value=locator), self.assertRaises(ActionError):
            await unique_visible(Mock(), Mock())

    async def test_done_requires_extraction(self):
        with self.assertRaisesRegex(ActionError, 'EXTRACTION'):
            await verify_done(Mock(), done(), {}, '12345', 1)

    async def test_done_checks_identity_and_stale_balance(self):
        page = Mock()
        page.get_by_role.return_value = visible()
        for values, message in [(['54321', '$4,231.12'], 'MEMBER_ID'), (['12345', '$0.00'], 'BALANCE')]:
            with patch('agent.executor.read_definition', AsyncMock(side_effect=values)):
                with self.assertRaisesRegex(ActionError, message):
                    await verify_done(page, done(), {'member_id': '12345', 'savings_balance': '$4,231.12'}, '12345', 1)

    async def test_success_returns_only_extracted_values(self):
        page = Mock()
        page.get_by_role.return_value = visible()
        outputs = {'member_id': '12345', 'savings_balance': '$4,231.12'}
        with patch('agent.executor.read_definition', AsyncMock(side_effect=['12345', '$4,231.12'])):
            result = await verify_done(page, done(), outputs, '12345', 4)
        self.assertEqual(result.outputs, outputs)
        self.assertEqual(result.status, 'success')

    async def test_not_found_requires_matching_ui_and_id(self):
        page = Mock(url='http://localhost:8000/member?member_id=99999')
        page.get_by_role.return_value = visible()
        page.get_by_text.return_value = visible()
        action = decision('done', result={'status': 'business_outcome', 'code': 'MEMBER_NOT_FOUND'}).next_action
        result = await verify_done(page, action, {}, '99999', 3)
        self.assertEqual(result.status, 'business_outcome')
        with self.assertRaises(ActionError):
            await verify_done(page, action, {}, '12345', 3)

    async def test_loop_bounds_and_invalid_responses(self):
        page = Mock(url='http://localhost:8000/')
        observation = Observation(page.url, 'textbox Member ID', '', '')
        scroll = decision('scroll', direction='down', pixels=100)
        for response, limit, expected, calls in [(scroll, 2, 'MAX_STEPS', 2),
                                                 (scroll, 10, 'REPEATED_ACTION', 3),
                                                 ({'bad': 'response'}, 10, 'REPEATED_FAILURE', 2)]:
            decider = SimpleNamespace(decide=AsyncMock(return_value=response), last_metadata={})
            with tempfile.TemporaryDirectory() as directory:
                evidence = Evidence(Path(directory) / 'run')
                with patch('agent.agent.observe', AsyncMock(return_value=observation)), \
                     patch('agent.agent.safe_snapshot', AsyncMock(return_value={})), \
                     patch('agent.agent.execute_action', AsyncMock(return_value='ACTION_COMPLETED')):
                    result = await discovery_loop(page, decider, 'Find savings balance for 12345', Policy(), evidence,
                                                  limit, time.monotonic() + 10, [])
                self.assertEqual(result.code, expected)
                self.assertEqual(decider.decide.await_count, calls)

    async def test_expired_deadline(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(TimeoutError):
            await discovery_loop(Mock(url='http://localhost:8000/'), Mock(), 'Find savings balance for 12345',
                                 Policy(), Evidence(Path(directory) / 'run'), 10, time.monotonic() - 1, [])

    async def test_openai_request_uses_schema_image_and_no_storage(self):
        from agent.decision import OpenAIDecider
        instance = OpenAIDecider.__new__(OpenAIDecider)
        instance.model = 'configured-model'
        reply = SimpleNamespace(id='test-response', usage=None, output_parsed=decision('scroll', direction='down', pixels=100))
        parse = AsyncMock(return_value=reply)
        instance.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        result = await instance.decide('goal', Observation('url', 'tree', 'text', 'aW1hZ2U='), [], {}, 10)
        self.assertIsInstance(result, Decision)
        arguments = parse.call_args.kwargs
        self.assertFalse(arguments['store'])
        self.assertIs(arguments['text_format'], Decision)
        self.assertEqual(arguments['input'][0]['content'][1]['type'], 'input_image')
        self.assertEqual(arguments['timeout'], 10)


if __name__ == '__main__':
    unittest.main()
