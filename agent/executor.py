"""Playwright adapter. Only this module translates targets to locators."""
import re
from urllib.parse import parse_qs, urlsplit
from .actions import RoleTarget, DefinitionTarget, RunResult


class ActionError(RuntimeError):
    pass


def resolve(page, target):
    if isinstance(target, RoleTarget):
        return page.get_by_role(target.role, name=target.name, exact=True)
    term = page.locator('dt').filter(has_text=re.compile(rf'^{re.escape(target.label)}$'))
    # Internal adapter implementation, never model-supplied XPath.
    return term.locator('xpath=following-sibling::dd[1]')


async def unique_visible(page, target):
    locator = resolve(page, target)
    if await locator.count() != 1:
        raise ActionError('TARGET_MISSING_OR_AMBIGUOUS')
    if not await locator.is_visible():
        raise ActionError('TARGET_NOT_VISIBLE')
    return locator


async def read_definition(page, label: str) -> str:
    locator = await unique_visible(page, DefinitionTarget(kind='definition', label=label))
    return (await locator.inner_text()).strip()


async def execute_action(page, action, outputs: dict[str, str]) -> str:
    kind = action.action
    if kind == 'scroll':
        await page.mouse.wheel(0, action.pixels * (1 if action.direction == 'down' else -1))
    elif kind == 'wait':
        locator = resolve(page, action.target)
        await locator.wait_for(state='visible')
        await unique_visible(page, action.target)
    elif kind == 'extract':
        locator = await unique_visible(page, action.target)
        outputs[action.output_name] = (await locator.inner_text()).strip()
    else:
        locator = await unique_visible(page, action.target)
        if kind == 'click':
            await locator.click()
        elif kind == 'type':
            await locator.fill(action.value)
        elif kind == 'keypress':
            await locator.press(action.key)
    return 'ACTION_COMPLETED'


async def verify_done(page, action, outputs, member_id: str, step: int) -> RunResult:
    result = action.result
    if result.status == 'failure':
        return RunResult(status='failure', code='UNABLE_TO_COMPLETE', step=step)
    if result.status == 'business_outcome':
        heading = page.get_by_role('heading', name='Member Not Found', exact=True)
        message = page.get_by_text(f'No member exists with ID {member_id}.', exact=True)
        query_id = parse_qs(urlsplit(page.url).query).get('member_id')
        if (await heading.count() != 1 or not await heading.is_visible()
                or await message.count() != 1 or not await message.is_visible()
                or query_id != [member_id]):
            raise ActionError('BUSINESS_OUTCOME_NOT_VERIFIED')
        return RunResult(status='business_outcome', code='MEMBER_NOT_FOUND', step=step)
    if set(result.output_keys) != {'member_id', 'savings_balance'}:
        raise ActionError('REQUIRED_OUTPUT_KEYS_MISSING')
    if set(outputs) != {'member_id', 'savings_balance'}:
        raise ActionError('REQUIRED_EXTRACTION_MISSING')
    heading = page.get_by_role('heading', name='Member Details', exact=True)
    if await heading.count() != 1 or not await heading.is_visible():
        raise ActionError('DETAILS_NOT_VISIBLE')
    visible_id = await read_definition(page, 'Member ID')
    balance = await read_definition(page, 'Current Savings Balance')
    if visible_id != member_id or outputs['member_id'] != member_id:
        raise ActionError('MEMBER_ID_MISMATCH')
    if balance != outputs['savings_balance'] or not re.fullmatch(r'\$\d{1,3}(?:,\d{3})*\.\d{2}|\$\d+\.\d{2}', balance):
        raise ActionError('BALANCE_NOT_VERIFIED')
    return RunResult(status='success', code='GOAL_VERIFIED', outputs=dict(outputs), step=step)
