"""Persist only approved structural metadata, never raw model/browser payloads."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REASONS = {
    'click': 'Activate an approved lookup control', 'type': 'Enter the requested lookup parameter',
    'keypress': 'Operate the selected lookup control', 'scroll': 'Inspect another part of the page',
    'wait': 'Wait for a named visible condition', 'extract': 'Read a declared output from the UI',
    'done': 'Request verification of the terminal result',
}


def safe_action(action):
    if action is None:
        return None
    data = action.model_dump()
    data['reason'] = REASONS[action.action]
    data['reason_source'] = 'code-generated; model prose omitted'
    if 'value' in data:
        data['value'] = '[REDACTED]'
    # Retain only known static labels; rejected names may contain sensitive text.
    if 'target' in data:
        target = data['target']
        known = {'Member ID', 'Member Name', 'Status', 'Account Number', 'Current Savings Balance',
                 'Search', 'Back to Search', 'Member Service Portal', 'Member Details',
                 'Member Not Found', 'Savings Account', 'Member Information', 'Find a member'}
        name = target.get('name', target.get('label'))
        data['target'] = {**target, ('name' if 'name' in target else 'label'): name if name in known else '[REDACTED]'}
    return data


class Evidence:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.path = directory / 'steps.jsonl'
        self.current_step = 0

    def write(self, **event):
        event['timestamp'] = datetime.now(timezone.utc).isoformat()
        if event.get('event') == 'step_started':
            self.current_step = event['step']
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=True) + '\n')

    def step(self, number, url, snapshot, action, outcome, outputs, metadata):
        # Full URLs can contain PII or secrets; retain only known route names.
        path = urlsplit(url).path
        self.write(event='step', step=number, route=path if path in ('/', '/member') else '[REDACTED]',
                   observation=snapshot, action=safe_action(action), execution_result=outcome,
                   extracted_values={key: '[REDACTED]' for key in outputs}, model=metadata)

    def record_capability_action(self, number, action, member_id):
        """Called only after successful execution and policy/result verification."""
        from .policy import Policy
        Policy().check_action(action, member_id)
        data = action.model_dump(exclude={'reason'})
        if action.action == 'type':
            # Policy above proves the typed value equals the caller's parameter.
            data['value'] = {'input': 'member_id'}
        self.write(event='capability_action', step=number, action=data)

    def failure_snapshot(self, snapshot):
        (self.directory / 'failure-dom.json').write_text(json.dumps(snapshot, indent=2), encoding='utf-8')

    def finish(self, result):
        safe = result.model_dump()
        safe['outputs'] = {key: '[REDACTED]' for key in result.outputs}
        self.write(event='result', result=safe)
