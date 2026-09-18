"""Compiler contract tests with synthetic logs in temporary directories only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from pydantic import ValidationError
from agent.actions import Decision
from agent.evidence import Evidence
from capabilities.compiler import compile_capability, CompileError
from capabilities.schema import Capability

ROOT = Path(__file__).resolve().parents[1]


def synthetic_events(missing=False, bound=True):
    """Test fixture, never emitted as project discovery evidence."""
    actions = [
        {'action': 'type', 'target': {'kind': 'role', 'role': 'textbox', 'name': 'Member ID'}, 'value': '[REDACTED]'},
        {'action': 'keypress', 'target': {'kind': 'role', 'role': 'button', 'name': 'Search'}, 'key': 'Enter'},
    ]
    if not missing:
        actions.extend([
            {'action': 'extract', 'target': {'kind': 'definition', 'label': 'Member ID'}, 'output_name': 'member_id'},
            {'action': 'extract', 'target': {'kind': 'definition', 'label': 'Current Savings Balance'}, 'output_name': 'savings_balance'},
        ])
    status = 'business_outcome' if missing else 'success'
    code = 'MEMBER_NOT_FOUND' if missing else 'GOAL_VERIFIED'
    terminal = {'status': status, 'code': code} if missing else {'status': status, 'output_keys': ['member_id', 'savings_balance']}
    actions.append({'action': 'done', 'result': terminal})
    events = [{'event': 'run_started', 'mode': 'live_llm', 'test_fixture': True}]
    for number, action in enumerate(actions, 1):
        events.append({'event': 'step_started', 'step': number})
        if bound:
            parameterized = copy.deepcopy(action)
            if action['action'] == 'type':
                parameterized['value'] = {'input': 'member_id'}
            events.append({'event': 'capability_action', 'step': number, 'action': parameterized})
        events.append({'event': 'step', 'step': number, 'action': dict(action, reason='Fixture'),
                       'execution_result': code if number == len(actions) else 'ACTION_COMPLETED',
                       'model': {'test_fixture': True},
                       'observation': {'controls': [{'role': 'heading', 'name': 'Member Not Found' if missing else 'Member Details', 'visible_matches': 1}]}})
    events.append({'event': 'result', 'result': {'status': status, 'code': code, 'step': len(actions),
                   'outputs': {} if missing else {'member_id': '[REDACTED]', 'savings_balance': '[REDACTED]'}}})
    return events


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.success = Path(self.temp.name) / 'discovery-aaaaaaaaaaaa' / 'steps.jsonl'
        self.missing = Path(self.temp.name) / 'discovery-bbbbbbbbbbbb' / 'steps.jsonl'
        self.save(self.success, synthetic_events())
        self.save(self.missing, synthetic_events(missing=True))

    def save(self, path, events):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(e) for e in events))

    def test_compile_round_trip_and_no_concrete_values(self):
        cap = compile_capability(self.success, self.missing)
        self.assertEqual(Capability.model_validate_json(cap.model_dump_json()), cap)
        self.assertEqual(cap.steps[0].value.input, 'member_id')
        self.assertEqual(cap.steps[2].not_found.code, 'MEMBER_NOT_FOUND')
        self.assertNotIn('[REDACTED]', cap.model_dump_json())
        self.assertEqual(cap.provenance.successful_run.binding, 'recorded_input_reference')

    def test_legacy_requires_explicit_opt_in(self):
        self.save(self.success, synthetic_events(bound=False))
        with self.assertRaises(CompileError):
            compile_capability(self.success, self.missing)
        cap = compile_capability(self.success, self.missing, allow_legacy=True)
        self.assertEqual(cap.provenance.successful_run.binding, 'legacy_enforced_policy_migration')

    def test_reject_incomplete_failed_and_mismatched_logs(self):
        for modification in ('failed_step', 'missing_result', 'wrong_outcome', 'binding', 'partial', 'missing_model', 'extra_attempt'):
            events = synthetic_events()
            if modification == 'failed_step':
                next(e for e in events if e['event'] == 'step')['execution_result'] = 'BROWSER_TIMEOUT'
            elif modification == 'missing_result':
                events.pop()
            elif modification == 'wrong_outcome':
                events[-1]['result']['code'] = 'UNABLE_TO_COMPLETE'
            elif modification == 'binding':
                next(e for e in events if e['event'] == 'capability_action')['action']['value'] = {'input': 'another_id'}
            elif modification == 'partial':
                events.pop(2)
            elif modification == 'missing_model':
                next(e for e in events if e['event'] == 'step')['model'] = {}
            else:
                events.insert(-1, {'event': 'step_started', 'step': 99})
            self.save(self.success, events)
            with self.subTest(modification=modification), self.assertRaises(CompileError):
                compile_capability(self.success, self.missing)

    def test_not_found_must_share_submission(self):
        events = synthetic_events(missing=True)
        for e in events:
            if e['event'] in ('step', 'capability_action') and e['step'] == 2:
                e['action']['target']['role'] = 'textbox'
                e['action']['target']['name'] = 'Member ID'
        self.save(self.missing, events)
        with self.assertRaises(CompileError):
            compile_capability(self.success, self.missing)

    def test_schema_rejects_broken_contracts(self):
        original = compile_capability(self.success, self.missing).model_dump()
        for change in ('duplicate_id', 'missing_input', 'wrong_output', 'no_checkpoint', 'version', 'literal_value', 'missing_success_output'):
            data = copy.deepcopy(original)
            if change == 'duplicate_id':
                data['steps'][1]['id'] = data['steps'][0]['id']
            elif change == 'missing_input':
                data['inputs'] = {}
            elif change == 'wrong_output':
                data['steps'][-1]['target']['label'] = 'Member Name'
            elif change == 'no_checkpoint':
                data['steps'].pop(2)
            elif change == 'version':
                data['schema_version'] = '2.0'
            elif change == 'literal_value':
                data['steps'][0]['value'] = '12345'
            else:
                data['success']['required_outputs'] = ['savings_balance']
            with self.subTest(change=change), self.assertRaises(ValidationError):
                Capability.model_validate(data)

    def test_recorder_binds_only_verified_parameter(self):
        evidence = Evidence(Path(self.temp.name) / 'recording')
        action = Decision.model_validate({'next_action': {'action': 'type', 'reason': 'private prose',
            'target': {'kind': 'role', 'role': 'textbox', 'name': 'Member ID'}, 'value': '12345'}}).next_action
        evidence.record_capability_action(1, action, '12345')
        content = evidence.path.read_text()
        self.assertNotIn('12345', content)
        self.assertNotIn('private prose', content)
        self.assertEqual(json.loads(content)['action']['value'], {'input': 'member_id'})
        with self.assertRaises(RuntimeError):
            evidence.record_capability_action(2, action, '54321')

    def test_delivered_artifact_has_valid_provenance(self):
        cap = Capability.model_validate_json((ROOT / 'capabilities/get_savings_balance.v1.json').read_text())
        self.assertEqual(cap.name, 'get_savings_balance')
        for source in (cap.provenance.successful_run, cap.provenance.not_found_run):
            self.assertEqual(len(source.sha256), 64)
