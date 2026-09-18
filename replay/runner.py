"""Replay a versioned capability without importing or calling a model provider."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlsplit, parse_qs

from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
from pydantic import ValidationError
from capabilities.schema import Capability, OutcomeStep
from agent.actions import Decision, RunResult
from agent.executor import execute_action, read_definition, ActionError
from agent.observer import safe_snapshot
from agent.evidence import Evidence
from agent.policy import Policy, PolicyError
from .handoff import Handoff, HandoffError


class ReplayError(RuntimeError):
    pass


def validate_input(capability, member_id):
    if not isinstance(member_id, str) or not re.fullmatch(capability.inputs['member_id'].pattern, member_id):
        raise ReplayError('INVALID_INPUT')


def bind_action(step, member_id):
    data = step.model_dump(exclude={'id'})
    if data['action'] == 'type':
        data['value'] = member_id
    return Decision.model_validate({'next_action': dict(data, reason='Execute recorded capability step')}).next_action


async def visible_count(locator):
    return sum([await locator.nth(i).is_visible() for i in range(await locator.count())])


async def await_outcome(page, checkpoint, member_id, policy, errors):
    deadline = time.monotonic() + checkpoint.timeout_ms / 1000
    while True:
        policy.check_url(page.url)
        if errors:
            raise ReplayError(errors[0])
        details = await visible_count(page.get_by_role('heading', name=checkpoint.details.heading, exact=True))
        missing = await visible_count(page.get_by_role('heading', name=checkpoint.not_found.heading, exact=True))
        if details > 1 or missing > 1 or (details and missing):
            raise ReplayError(checkpoint.on_ambiguous)
        if details:
            if await read_definition(page, checkpoint.details.member_label) != member_id:
                raise ReplayError('MEMBER_ID_MISMATCH')
            return 'DETAILS_VERIFIED'
        if missing:
            message = page.get_by_text(checkpoint.not_found.message_template.format(member_id=member_id), exact=True)
            query_id = parse_qs(urlsplit(page.url).query).get(checkpoint.not_found.member_query_parameter)
            if await visible_count(message) != 1 or query_id != [member_id]:
                raise ReplayError('BUSINESS_OUTCOME_NOT_VERIFIED')
            return checkpoint.not_found.code
        if await visible_count(page.get_by_role('alert')):
            raise ReplayError('APPLICATION_VALIDATION_ERROR')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReplayError(checkpoint.on_timeout)
        # Bounded condition polling, not a fixed delay used to assume a page loaded.
        await asyncio.sleep(min(.1, remaining))


async def verify_success(page, capability, outputs, member_id):
    contract = capability.success
    if await visible_count(page.get_by_role('heading', name=contract.heading, exact=True)) != 1:
        raise ReplayError('DETAILS_NOT_VISIBLE')
    if set(outputs) != set(contract.required_outputs):
        raise ReplayError('OUTPUTS_MISSING')
    if outputs.get(contract.identity_output) != member_id:
        raise ReplayError('MEMBER_ID_MISMATCH')
    for name, spec in capability.outputs.items():
        if not re.fullmatch(spec.pattern, outputs[name]):
            raise ReplayError('OUTPUT_FORMAT_MISMATCH')
        if contract.recheck_outputs_against_live_ui and await read_definition(page, spec.source.label) != outputs[name]:
            raise ReplayError('STALE_OUTPUT')


async def execute_flow(page, capability, member_id, policy, evidence, errors, start_index=0):
    validate_input(capability, member_id)
    outputs = {}
    for index, step in enumerate(capability.steps, 1):
        if index <= start_index:
            continue
        evidence.write(event='step_started', step=index)
        policy.check_url(page.url)
        if errors:
            raise ReplayError(errors[0])
        snapshot = await safe_snapshot(page)
        if isinstance(step, OutcomeStep):
            if 'wait' not in policy.allowed_actions:
                raise PolicyError('Waiting is not allowed')
            outcome = await await_outcome(page, step, member_id, policy, errors)
            evidence.write(event='checkpoint', step=index, checkpoint='lookup_outcome',
                           observation=snapshot, execution_result=outcome)
            print(f'Step {index}: await_outcome -> {outcome}', flush=True)
            if outcome == 'MEMBER_NOT_FOUND':
                return RunResult(status='business_outcome', code=outcome, step=index)
        else:
            action = bind_action(step, member_id)
            policy.check_action(action, member_id)
            await execute_action(page, action, outputs)
            policy.check_url(page.url)
            if errors:
                raise ReplayError(errors[0])
            evidence.step(index, page.url, snapshot, action, 'ACTION_COMPLETED', outputs, {})
            print(f'Step {index}: {step.action} -> ACTION_COMPLETED', flush=True)
    await verify_success(page, capability, outputs, member_id)
    policy.check_url(page.url)
    if errors:
        raise ReplayError(errors[0])
    evidence.write(event='checkpoint', step=len(capability.steps), checkpoint='terminal_success', execution_result='GOAL_VERIFIED')
    return RunResult(status='success', code='GOAL_VERIFIED', outputs=outputs, step=len(capability.steps))


def failed(code, step):
    return RunResult(status='failure', code=code, step=step,
                     expected='Recorded control, supported outcome, and verified declared outputs', observed=code)


async def run_replay(args, capability, policy, evidence):
    browser = page = None
    errors = []
    result = failed('REPLAY_FAILED', 0)
    try:
        validate_input(capability, args.member_id)
        parsed = urlsplit(args.url)
        if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise PolicyError('Supply only the configured portal origin')
        entry = args.url.rstrip('/') + capability.entry_path
        policy.check_url(entry)
        async with async_playwright() as playwright:
            try:
                async with asyncio.timeout(args.timeout):
                    browser = await playwright.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
                    context = await browser.new_context(accept_downloads=False, service_workers='block')

                    async def guard(route):
                        try:
                            policy.check_url(route.request.url)
                            if route.request.method != 'GET':
                                raise PolicyError('Only GET is allowed')
                        except PolicyError:
                            if not route.request.url.endswith('/favicon.ico'):
                                errors.append('POLICY_BLOCKED_REQUEST')
                            await route.abort()
                            return
                        await route.continue_()

                    await context.route('**/*', guard)
                    page = await context.new_page()
                    page.set_default_timeout(10000)

                    async def dialog_seen(dialog):
                        errors.append('UNEXPECTED_DIALOG')
                        await dialog.dismiss()

                    page.on('dialog', dialog_seen)
                    page.on('popup', lambda _: errors.append('UNEXPECTED_POPUP'))
                    page.on('download', lambda _: errors.append('UNEXPECTED_DOWNLOAD'))
                    page.on('pageerror', lambda _: errors.append('PAGE_SCRIPT_ERROR'))
                    page.on('response', lambda response: errors.append('HTTP_ERROR')
                            if response.status >= 400 and response.request.resource_type in ('document', 'stylesheet') else None)
                    # One bounded retry of initial navigation on timeout only. Never resubmit blindly.
                    for attempt in range(2):
                        try:
                            response = await page.goto(entry, wait_until='domcontentloaded')
                            break
                        except BrowserTimeout:
                            if attempt:
                                raise
                            evidence.write(event='recovery', step=0, code='ENTRY_LOAD_RETRY', attempt=1)
                    if response is None or not response.ok:
                        raise ReplayError('ENTRY_PAGE_FAILED')
                    handoff = None
                    if getattr(args, 'human_handoff', False):
                        handoff = Handoff(page, policy, evidence, errors, timeout=args.handoff_timeout)
                        await handoff.install()
                    checkpoint = next(s for s in capability.steps if isinstance(s, OutcomeStep))
                    async def verify_resume():
                        # Short verification: if not ready, the human retains control.
                        await await_outcome(page, checkpoint.model_copy(update={'timeout_ms': 1000}),
                                            args.member_id, policy, errors)
                    start_index = 0
                    if getattr(args, 'demo_handoff', False):
                        await handoff.request('DEMO_MANUAL_LOOKUP_REQUIRED', verify_resume)
                        start_index = 2
                    while True:
                        try:
                            result = await execute_flow(page, capability, args.member_id, policy, evidence, errors, start_index)
                            break
                        except (ActionError, BrowserTimeout, ReplayError) as exc:
                            recoverable = isinstance(exc, (ActionError, BrowserTimeout)) or str(exc) in {
                                'UNEXPECTED_STATE_OR_TIMEOUT', 'APPLICATION_VALIDATION_ERROR',
                                'MEMBER_ID_MISMATCH', 'DETAILS_NOT_VISIBLE', 'STALE_OUTPUT',
                                'BUSINESS_OUTCOME_NOT_VERIFIED', 'OUTPUT_FORMAT_MISMATCH'}
                            if not handoff or not recoverable or errors:
                                raise
                            reason = 'BROWSER_TIMEOUT' if isinstance(exc, BrowserTimeout) else str(exc)
                            await handoff.request(reason, verify_resume)
                            # Clear outputs and restart at the read-only outcome checkpoint.
                            start_index = 2
            finally:
                if page is not None:
                    try:
                        async with asyncio.timeout(2):
                            policy.check_url(page.url)
                            snapshot = await safe_snapshot(page)
                    except Exception:
                        snapshot = {'state': 'snapshot_unavailable', 'sensitive_content': 'omitted'}
                    if result.status == 'failure':
                        evidence.failure_snapshot(snapshot)
                if browser is not None:
                    try:
                        async with asyncio.timeout(5):
                            await browser.close()
                    except Exception:
                        pass
    except (ReplayError, ActionError, HandoffError) as exc:
        result = failed(str(exc), evidence.current_step)
    except PolicyError:
        result = failed('POLICY_BLOCKED', evidence.current_step)
    except BrowserTimeout:
        result = failed('BROWSER_TIMEOUT', evidence.current_step)
    except TimeoutError:
        result = failed('OVERALL_TIMEOUT', evidence.current_step)
    except Exception:
        result = failed('BROWSER_LAUNCH_FAILED' if browser is None else 'REPLAY_RUNTIME_ERROR', evidence.current_step)
    if result.status == 'failure':
        evidence.write(event='step_failed', step=result.step, code=result.code)
        if not (evidence.directory / 'failure-dom.json').exists():
            evidence.failure_snapshot({'state': 'browser_not_available', 'sensitive_content': 'omitted'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, default=Path('capabilities/get_savings_balance.v1.json'))
    parser.add_argument('--member-id', required=True)
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--policy', type=Path, default=Path(__file__).resolve().parents[1] / 'agent/policy.json')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--slow-mo', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--human-handoff', action='store_true', help='Pause on recoverable blocks for same-session manual control')
    parser.add_argument('--demo-handoff', action='store_true', help='Explicit demo: ask the human to perform the lookup before replay extraction')
    parser.add_argument('--handoff-timeout', type=float, default=180)
    parser.add_argument('--evidence-dir', type=Path, default=Path('evidence'))
    args = parser.parse_args()
    if args.demo_handoff:
        args.human_handoff = True
    if args.human_handoff and not args.headed:
        parser.error('Human handoff requires --headed')
    if args.handoff_timeout <= 0:
        parser.error('Handoff timeout must be positive')
    if args.timeout <= 0 or args.slow_mo < 0:
        parser.error('Timeout must be positive and slow-mo nonnegative')
    evidence = Evidence(args.evidence_dir / ('replay-' + uuid.uuid4().hex[:12]))
    try:
        raw = args.artifact.read_bytes()
        capability = Capability.model_validate_json(raw)
        policy = Policy.model_validate_json(args.policy.read_text())
    except (OSError, ValueError, ValidationError):
        result = failed('INVALID_ARTIFACT_OR_POLICY', 0)
        evidence.write(event='run_started', mode='deterministic_replay', model_calls=0)
    else:
        evidence.write(event='run_started', mode='deterministic_replay', model_calls=0,
                       capability=capability.name, version=capability.capability_version,
                       artifact_sha256=hashlib.sha256(raw).hexdigest(), human_handoff=args.human_handoff, demo_handoff=args.demo_handoff)
        local = Path(__file__).resolve().parents[1] / '.venv/playwright-browsers'
        if local.is_dir():
            os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(local))
        result = asyncio.run(run_replay(args, capability, policy, evidence))
    evidence.finish(result)
    print(json.dumps(result.model_dump(), indent=2))
    print(f'Redacted evidence: {evidence.directory}')
    return 1 if result.status == 'failure' else 0


if __name__ == '__main__':
    raise SystemExit(main())
