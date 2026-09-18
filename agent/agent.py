"""Bounded discovery loop and command-line entry point."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import time
import uuid

from pydantic import ValidationError
from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
from .actions import Decision, RunResult
from .decision import DecisionError, OpenAIDecider
from .ollama import OllamaDecider, OllamaError
from .evidence import Evidence
from .executor import ActionError, execute_action, verify_done
from .observer import observe, safe_snapshot
from .policy import Policy, PolicyError


class RuntimeFailure(RuntimeError):
    pass


def requested_member(goal: str) -> str:
    ids = re.findall(r'(?<!\d)[0-9]{5}(?!\d)', goal)
    if len(set(ids)) != 1 or not re.search(r'\bsavings\b', goal, re.I) or not re.search(r'\bbalance\b', goal, re.I):
        raise ValueError('This milestone supports savings-balance lookup goals containing one five-digit member ID.')
    return ids[0]


def failure(code: str, step: int) -> RunResult:
    return RunResult(status='failure', code=code, step=step,
                     expected='Verified lookup result within the configured policy and limits', observed=code)


async def discovery_loop(page, decider, goal, policy, evidence, max_steps, deadline, runtime_errors):
    member_id = requested_member(goal)
    outputs, history = {}, []
    previous, repeated, consecutive_errors = None, 0, 0
    last_snapshot = {'format': 'sanitized-dom-summary-v1', 'state': 'not_observed'}
    result = failure('MAX_STEPS', 0)
    for step in range(1, max_steps + 1):
        evidence.write(event='step_started', step=step)
        policy.check_url(page.url)
        if runtime_errors:
            raise RuntimeFailure(runtime_errors[0])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        page.set_default_timeout(min(5000, remaining * 1000))
        observation = await observe(page)
        policy.check_url(observation.url)
        last_snapshot = await safe_snapshot(page)
        action = None
        try:
            decision = await decider.decide(goal, observation, history, outputs, deadline - time.monotonic())
            # Validate again at the trust boundary, including injected test deciders.
            decision = Decision.model_validate(decision.model_dump() if isinstance(decision, Decision) else decision)
            action = decision.next_action
            policy.check_action(action, member_id)
            signature = (observation.url, observation.accessible_page, action.model_dump_json(exclude={'reason'}))
            repeated = repeated + 1 if signature == previous else 1
            previous = signature
            if repeated >= 3:
                result = failure('REPEATED_ACTION', step)
                evidence.step(step, page.url, last_snapshot, action, result.code, outputs, {})
                break
            # Clear extracted evidence on interactions: never reuse stale values after a new lookup.
            if action.action in ('click', 'type', 'keypress'):
                outputs.clear()
            if action.action == 'done':
                result = await verify_done(page, action, outputs, member_id, step)
                outcome = result.code
            else:
                outcome = await execute_action(page, action, outputs)
            policy.check_url(page.url)
            if runtime_errors:
                raise RuntimeFailure(runtime_errors[0])
            consecutive_errors = 0
        except (ActionError, BrowserTimeout, ValidationError, DecisionError) as exc:
            consecutive_errors += 1
            result = failure('MAX_STEPS', step)
            outcome = (str(exc) if isinstance(exc, (ActionError, DecisionError)) else
                       'BROWSER_TIMEOUT' if isinstance(exc, BrowserTimeout) else 'INVALID_MODEL_ACTION')
            history.append({'step': step, 'action': action.model_dump() if action else None, 'result': outcome})
            evidence.step(step, page.url, last_snapshot, action, outcome, outputs, {})
            if consecutive_errors >= 2:
                result = failure('REPEATED_FAILURE', step)
                break
            continue
        except PolicyError:
            evidence.step(step, page.url, last_snapshot, action, 'POLICY_BLOCKED', outputs, {})
            result = failure('POLICY_BLOCKED', step)
            break
        except (RuntimeFailure, OllamaError) as exc:
            result = failure(str(exc), step)
            evidence.step(step, page.url, last_snapshot, action, result.code, outputs, {})
            break
        except Exception:
            evidence.step(step, page.url, last_snapshot, action, 'PROVIDER_OR_EXECUTION_ERROR', outputs, {})
            raise
        evidence.record_capability_action(step, action, member_id)
        evidence.step(step, page.url, last_snapshot, action, outcome, outputs,
                      getattr(decider, 'last_metadata', {}))
        history.append({'step': step, 'action': action.model_dump(), 'result': outcome})
        print(f'Step {step}: {action.action} -> {outcome}', flush=True)
        if action.action == 'done':
            break
        result = failure('MAX_STEPS', step)
    if result.status == 'failure':
        evidence.failure_snapshot(last_snapshot)
    return result


async def run_agent(args, evidence, decider):
    policy = Policy.model_validate_json(Path(args.policy).read_text())
    policy.check_url(args.url)
    requested_member(args.goal)
    browser = context = page = None
    runtime_errors = []
    async with async_playwright() as playwright:
        try:
            deadline = time.monotonic() + args.timeout
            async with asyncio.timeout(args.timeout):
                browser = await playwright.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
                context = await browser.new_context(viewport={'width': 1280, 'height': 900},
                                                    accept_downloads=False, service_workers='block')

                async def route_request(route):
                    try:
                        policy.check_url(route.request.url)
                        if route.request.method != 'GET':
                            raise PolicyError('Only GET is allowed')
                    except PolicyError:
                        # Browsers may request an irrelevant favicon; never fetch it.
                        if not route.request.url.endswith('/favicon.ico'):
                            runtime_errors.append('POLICY_BLOCKED_REQUEST')
                        await route.abort()
                        return
                    await route.continue_()

                await context.route('**/*', route_request)
                page = await context.new_page()
                page.set_default_timeout(5000)

                async def dismiss_dialog(dialog):
                    runtime_errors.append('UNEXPECTED_DIALOG')
                    await dialog.dismiss()

                page.on('dialog', dismiss_dialog)
                page.on('popup', lambda _: runtime_errors.append('UNEXPECTED_POPUP'))
                page.on('download', lambda _: runtime_errors.append('UNEXPECTED_DOWNLOAD'))
                page.on('pageerror', lambda _: runtime_errors.append('PAGE_SCRIPT_ERROR'))
                page.on('response', lambda response: runtime_errors.append('HTTP_ERROR')
                        if response.status >= 400 and response.request.resource_type in ('document', 'stylesheet') else None)
                response = await page.goto(args.url, wait_until='domcontentloaded')
                if response is None or not response.ok:
                    raise RuntimeFailure('ENTRY_PAGE_FAILED')
                result = await discovery_loop(page, decider, args.goal, policy, evidence,
                                              args.max_steps, deadline, runtime_errors)
        except TimeoutError:
            result = failure('OVERALL_TIMEOUT', evidence.current_step)
        except PolicyError:
            result = failure('POLICY_BLOCKED', evidence.current_step)
        except RuntimeFailure as exc:
            result = failure(str(exc), evidence.current_step)
        except Exception as exc:
            # Exception messages may contain API secrets, page values, or echoed model output.
            codes = {'AuthenticationError': 'MODEL_AUTHENTICATION_FAILED',
                     'PermissionDeniedError': 'MODEL_PERMISSION_DENIED',
                     'RateLimitError': 'MODEL_RATE_LIMIT_OR_QUOTA',
                     'NotFoundError': 'MODEL_NOT_FOUND', 'BadRequestError': 'MODEL_REQUEST_REJECTED',
                     'APIConnectionError': 'MODEL_CONNECTION_FAILED', 'APITimeoutError': 'MODEL_TIMEOUT'}
            code = codes.get(type(exc).__name__, 'BROWSER_LAUNCH_FAILED' if browser is None else 'RUNTIME_OR_PROVIDER_ERROR')
            result = failure(code, evidence.current_step)
            print(f'Run stopped: {type(exc).__name__}. Check browser launch, API access, model and portal availability.', flush=True)
        finally:
            if page is not None and 'result' in locals() and result.status == 'failure':
                try:
                    async with asyncio.timeout(2):
                        policy.check_url(page.url)
                        evidence.failure_snapshot(await safe_snapshot(page))
                except Exception:
                    evidence.failure_snapshot({'state': 'snapshot_unavailable', 'sensitive_content': 'omitted'})
            elif 'result' in locals() and result.status == 'failure':
                evidence.failure_snapshot({'state': 'browser_unavailable', 'sensitive_content': 'omitted'})
            if browser is not None:
                try:
                    async with asyncio.timeout(5):
                        await browser.close()
                except Exception:
                    pass
    return result


def parser():
    cli = argparse.ArgumentParser(description='Run a real LLM-driven savings-balance lookup.')
    cli.add_argument('--goal', required=True)
    cli.add_argument('--url', default='http://localhost:8000/')
    cli.add_argument('--provider', choices=['ollama', 'openai'], default='ollama')
    cli.add_argument('--model', help='Defaults to qwen3-vl:4b-instruct for Ollama')
    cli.add_argument('--ollama-url', default='http://localhost:11434')
    cli.add_argument('--headed', action='store_true')
    cli.add_argument('--slow-mo', type=int, default=0)
    cli.add_argument('--max-steps', type=int, default=10)
    cli.add_argument('--timeout', type=float, default=600, help='Overall run budget in seconds')
    cli.add_argument('--policy', default=str(Path(__file__).with_name('policy.json')))
    cli.add_argument('--evidence-dir', type=Path, default=Path('evidence'))
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    args.model = args.model or (os.getenv('OLLAMA_MODEL', 'qwen3-vl:4b-instruct') if args.provider == 'ollama' else os.getenv('OPENAI_MODEL'))
    if not args.model:
        cli.error('Set OPENAI_MODEL or pass --model.')
    if args.provider == 'openai' and not os.getenv('OPENAI_API_KEY'):
        cli.error('Set OPENAI_API_KEY in your terminal; do not put it in code or commit it.')
    if args.max_steps < 1 or args.timeout <= 0 or args.slow_mo < 0:
        cli.error('Steps and timeout must be positive; slow-mo must be nonnegative.')
    try:
        requested_member(args.goal)
        Policy.model_validate_json(Path(args.policy).read_text()).check_url(args.url)
    except (ValueError, PolicyError, OSError) as exc:
        cli.error('Invalid goal, policy, or URL: use a savings-balance goal with one five-digit member ID and an allowed portal URL.')
    local = Path(__file__).resolve().parents[1] / '.venv' / 'playwright-browsers'
    if local.is_dir():
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(local))
    evidence = Evidence(args.evidence_dir / ('discovery-' + uuid.uuid4().hex[:12]))
    evidence.write(event='run_started', schema_version=1, mode='live_llm', max_steps=args.max_steps,
                   timeout_seconds=args.timeout, model=args.model, provider=args.provider)

    async def run():
        decider = (OllamaDecider(args.model, args.ollama_url) if args.provider == 'ollama'
                   else OpenAIDecider(args.model))
        try:
            return await run_agent(args, evidence, decider)
        finally:
            await decider.close()

    result = asyncio.run(run())
    evidence.finish(result)
    # Requested outputs are returned to the caller, but not persisted by the logger.
    print(json.dumps(result.model_dump(), indent=2))
    print(f'Redacted evidence: {evidence.directory}')
    return 1 if result.status == 'failure' else 0


if __name__ == '__main__':
    raise SystemExit(main())
