"""Single-operator terminal handoff for the same live browser page."""
import asyncio
import sys
from agent.observer import safe_snapshot
from agent.policy import PolicyError


class HandoffError(RuntimeError):
    pass


async def terminal_command():
    """POSIX stdin readiness: cancellable, without a stuck input() worker thread."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    def ready():
        if not future.done():
            future.set_result(sys.stdin.readline().strip().lower())
    loop.add_reader(sys.stdin.fileno(), ready)
    try:
        return await future
    finally:
        loop.remove_reader(sys.stdin.fileno())


# Fixed instrumentation observes interaction categories only; never input values.
RECORDER = r"""(() => {
  if (window.__handoffInstalled) return;
  window.__handoffInstalled = true;
  window.__handoffPending = new Set();
  const send = (data) => {
    const task = window.recordManualAction(data).catch(() => {});
    window.__handoffPending.add(task);
    task.finally(() => window.__handoffPending.delete(task));
  };
  for (const event of ['click', 'input', 'keydown']) {
    document.addEventListener(event, e => {
      if (!e.isTrusted) return;
      const el = e.target.closest?.('input,button,a') || e.target;
      let control = 'other';
      if (el.tagName === 'INPUT' && el.name === 'member_id') control = 'Member ID';
      if (el.tagName === 'BUTTON' && el.textContent.trim() === 'Search') control = 'Search';
      if (el.tagName === 'A' && el.textContent.trim() === 'Back to Search') control = 'Back to Search';
      const key = event === 'keydown' ? (['Enter','Tab','Escape'].includes(e.key) ? e.key : 'redacted') : null;
      send({event, control, key});
    }, true);
  }
})()"""


class Handoff:
    def __init__(self, page, policy, evidence, errors, timeout=180, max_interventions=2, reader=terminal_command):
        self.page, self.policy, self.evidence, self.errors = page, policy, evidence, errors
        self.timeout, self.max_interventions, self.reader = timeout, max_interventions, reader
        self.owner = 'automation'
        self.count = 0

    async def install(self):
        async def record(source, data):
            if self.owner != 'human' or source.get('page') != self.page or not isinstance(data, dict):
                return
            event = data.get('event')
            if event not in ('click', 'input', 'keydown'):
                return
            control = data.get('control')
            if control not in ('Member ID', 'Search', 'Back to Search'):
                control = 'other'
            key = data.get('key')
            if key not in ('Enter', 'Tab', 'Escape', None):
                key = 'redacted'
            self.evidence.write(event='human_action', intervention=self.count,
                                interaction=event, control=control, key=key)
        await self.page.expose_binding('recordManualAction', record)
        await self.page.add_init_script(RECORDER)
        await self.page.evaluate(RECORDER)
        def navigation(frame):
            if self.owner == 'human' and frame == self.page.main_frame:
                self.evidence.write(event='human_navigation', intervention=self.count, destination='redacted')
        self.page.on('framenavigated', navigation)

    async def request(self, reason, verify):
        if self.owner != 'automation' or self.count >= self.max_interventions:
            raise HandoffError('HANDOFF_LIMIT_REACHED')
        self.policy.check_url(self.page.url)
        if self.errors:
            raise HandoffError('HANDOFF_BLOCKED_BY_RUNTIME_ERROR')
        self.count += 1
        self.evidence.write(event='intervention_requested', intervention=self.count,
                            step=self.evidence.current_step, capability='get_savings_balance',
                            reason=reason, observation=await safe_snapshot(self.page))
        self.owner = 'human'
        self.evidence.write(event='control_transferred', owner='human', intervention=self.count)
        print('\nHUMAN CONTROL: automation is paused. In this browser, search for the requested member\n'
              'and reach Member Details or Member Not Found. Then type resume here, or abort.\n'
              'Resume rechecks identity and the page; it does not assume the manual steps worked.', flush=True)
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    command = await self.reader()
                    if command in ('abort', ''):
                        raise HandoffError('HUMAN_ABORTED')
                    if command != 'resume':
                        print('Type resume or abort.', flush=True)
                        continue
                    self.policy.check_url(self.page.url)
                    if self.errors:
                        raise HandoffError('HANDOFF_BLOCKED_BY_RUNTIME_ERROR')
                    # Drain pending recorder callbacks before transferring ownership.
                    await self.page.evaluate('async () => { await Promise.all(window.__handoffPending || []); }')
                    try:
                        await verify()
                    except PolicyError:
                        # Policy failures never become a request to try resume again.
                        raise
                    except (TimeoutError, RuntimeError) as exc:
                        # Keep control with the human; do not log raw page/exception data.
                        self.evidence.write(event='resume_rejected', intervention=self.count, code='CHECKPOINT_NOT_VERIFIED')
                        print('Resume rejected: reach the requested member result, then try resume again.', flush=True)
                        continue
                    self.policy.check_url(self.page.url)
                    if self.errors:
                        raise HandoffError('HANDOFF_BLOCKED_BY_RUNTIME_ERROR')
                    self.owner = 'automation'
                    self.evidence.write(event='control_transferred', owner='automation', intervention=self.count,
                                        checkpoint='lookup_outcome_verified')
                    return
        except TimeoutError as exc:
            raise HandoffError('HUMAN_TIMEOUT') from exc
        finally:
            if self.owner == 'human':
                self.owner = 'stopped'
                self.evidence.write(event='control_transferred', owner='stopped', intervention=self.count)
