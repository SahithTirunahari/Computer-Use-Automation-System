"""Compile trusted local discovery evidence; never call a model or browser."""
import argparse
import hashlib
import json
from pathlib import Path

from agent.actions import Decision
from agent.policy import Policy
from .schema import (Capability, InputContract, OutputContract, TypeStep, ClickStep,
                     KeyStep, ExtractStep, OutcomeStep, Provenance, SourceRun, BALANCE_PATTERN)


class CompileError(ValueError):
    pass


def load_run(path: Path, expected: str, allow_legacy: bool):
    raw = path.read_bytes()
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    if not events or events[0].get('event') != 'run_started' or events[0].get('mode') != 'live_llm':
        raise CompileError('A genuine live_llm discovery log is required')
    results = [e for e in events if e.get('event') == 'result']
    if len(results) != 1 or events[-1] != results[0]:
        raise CompileError('Run must have exactly one final result')
    result = results[0]['result']
    status = 'success' if expected == 'GOAL_VERIFIED' else 'business_outcome'
    if result.get('status') != status or result.get('code') != expected:
        raise CompileError('Run did not reach the required verified outcome')
    rows = [e for e in events if e.get('event') == 'step']
    expected_count = 5 if expected == 'GOAL_VERIFIED' else 3
    if len(rows) != expected_count or [r.get('step') for r in rows] != list(range(1, expected_count + 1)):
        raise CompileError('Version 1 accepts only a clean lookup sequence without recovery attempts')
    starts = [e.get('step') for e in events if e.get('event') == 'step_started']
    if starts != list(range(1, expected_count + 1)) or result.get('step') != expected_count:
        raise CompileError('Incomplete or inconsistent step sequence')
    recordings = [e for e in events if e.get('event') == 'capability_action']
    by_step = {e['step']: e for e in recordings}
    if len(by_step) != len(recordings):
        raise CompileError('Duplicate parameterized recordings')
    if recordings and set(by_step) != set(range(1, expected_count + 1)):
        raise CompileError('Partial parameterized recording')
    legacy = not recordings
    if legacy and not allow_legacy:
        raise CompileError('Old log has no input binding. Rerun discovery or explicitly use --legacy-policy-binding')
    actions = []
    for row in rows:
        if row.get('execution_result') != (expected if row['step'] == expected_count else 'ACTION_COMPLETED'):
            raise CompileError('Failed or unverified steps cannot be compiled')
        logged = dict(row['action'])
        logged.pop('reason_source', None)
        if logged.get('action') == 'type':
            if logged.get('value') != '[REDACTED]':
                raise CompileError('Expected privacy-preserving diagnostic log')
            logged['value'] = '00000'  # Validation sentinel only; never serialized.
        action = Decision.model_validate({'next_action': logged}).next_action
        Policy().check_action(action, '00000')
        normalized = action.model_dump(exclude={'reason'})
        if action.action == 'type':
            normalized['value'] = {'input': 'member_id'}
        if not legacy and by_step[row['step']].get('action') != normalized:
            raise CompileError('Parameterized recording disagrees with executed action')
        if not row.get('model'):
            raise CompileError('Missing model-call evidence')
        actions.append(normalized)
    if [a['action'] for a in actions[:2]] not in (['type', 'keypress'], ['type', 'click']):
        raise CompileError('Lookup must start with typing and submission')
    if actions[-1]['action'] != 'done':
        raise CompileError('Missing verified completion action')
    final = actions[-1]['result']
    if final.get('status') != status:
        raise CompileError('Completion action disagrees with verified result')
    if expected == 'GOAL_VERIFIED':
        if sorted(final.get('output_keys', [])) != ['member_id', 'savings_balance']:
            raise CompileError('Completion must reference both outputs')
        if set(result.get('outputs', {})) != {'member_id', 'savings_balance'}:
            raise CompileError('Verified outputs missing')
    elif final.get('code') != expected or result.get('outputs') != {}:
        raise CompileError('Invalid business-outcome completion')
    heading = 'Member Details' if expected == 'GOAL_VERIFIED' else 'Member Not Found'
    controls = rows[-1].get('observation', {}).get('controls', [])
    if {'role': 'heading', 'name': heading, 'visible_matches': 1} not in controls:
        raise CompileError('Terminal UI evidence is missing')
    source = SourceRun(run_id=path.parent.name, sha256=hashlib.sha256(raw).hexdigest(), outcome=expected,
                      binding='legacy_enforced_policy_migration' if legacy else 'recorded_input_reference')
    return actions, source


def compile_capability(success_path: Path, not_found_path: Path, allow_legacy=False) -> Capability:
    actions, source = load_run(success_path, 'GOAL_VERIFIED', allow_legacy)
    missing, missing_source = load_run(not_found_path, 'MEMBER_NOT_FOUND', allow_legacy)
    if actions[:2] != missing[:2]:
        raise CompileError('Not-found evidence must exercise the same parameterized submission')
    steps = []
    for index, action in enumerate(actions[:-1]):
        data = dict(action, id=f'step_{index + 1}')
        kind = action['action']
        cls = {'type': TypeStep, 'click': ClickStep, 'keypress': KeyStep, 'extract': ExtractStep}.get(kind)
        if cls is None:
            raise CompileError('Unsupported discovery action for version 1')
        steps.append(cls.model_validate(data))
        if index == 1:
            steps.append(OutcomeStep(id='check_lookup_outcome'))
    return Capability(
        inputs={'member_id': InputContract()},
        outputs={
            'member_id': OutputContract(source={'kind': 'definition', 'label': 'Member ID'}, pattern='^[0-9]{5}$'),
            'savings_balance': OutputContract(source={'kind': 'definition', 'label': 'Current Savings Balance'}, pattern=BALANCE_PATTERN),
        }, steps=steps, provenance=Provenance(successful_run=source, not_found_run=missing_source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--success-run', required=True, type=Path, help='Path to discovery steps.jsonl')
    parser.add_argument('--not-found-run', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('capabilities/get_savings_balance.v1.json'))
    parser.add_argument('--legacy-policy-binding', action='store_true',
                        help='Explicit migration for older logs whose typing policy enforced the requested member ID')
    args = parser.parse_args()
    try:
        capability = compile_capability(args.success_run, args.not_found_run, args.legacy_policy_binding)
        payload = capability.model_dump_json(indent=2) + '\n'
        # Revalidate the serialized contract and never silently overwrite a capability.
        Capability.model_validate_json(payload)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(payload)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'Compilation failed ({type(exc).__name__}): check input evidence, binding mode, schema, and output path.\n')
    print(f'Created {args.output}: {len(capability.steps)} steps, parameter member_id, two outputs, verified not-found branch.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
