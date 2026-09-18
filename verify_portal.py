"""Check the running Member Service Portal through Chromium's UI."""
import argparse
import os
from pathlib import Path
import re
import sys
# Use project-local browser downloads when available.
local_browsers = Path(__file__).resolve().parent / '.venv' / 'playwright-browsers'
if local_browsers.is_dir():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(local_browsers))

from playwright.sync_api import expect, sync_playwright

LABELS = ('Member ID', 'Member Name', 'Status', 'Account Number', 'Current Savings Balance')
CASES = [
    ('12345', ('12345', 'Alice Johnson', 'Active', 'SAV-1001', '$4,231.12')),
    ('54321', ('54321', 'Bob Smith', 'Active', 'SAV-2002', '$850.50')),
    ('77777', ('77777', 'Carol Williams', 'Restricted', 'SAV-3003', '$12,450.00')),
    ('99999', 'No member exists with ID 99999.'),
    ('', 'Please enter a Member ID.'),
    ('abc', 'Member ID must contain exactly 5 digits.'),
]


def check_case(page, base_url, member_id, expected):
    response = page.goto(base_url)
    if response is None or not response.ok:
        raise RuntimeError('Portal failed to load successfully')
    textbox = page.get_by_role('textbox', name='Member ID', exact=True)
    expect(textbox).to_be_visible()
    textbox.fill(member_id)
    with page.expect_navigation(wait_until='domcontentloaded') as navigation:
        page.get_by_role('button', name='Search', exact=True).click()
    response = navigation.value
    if response is None or not response.ok:
        raise RuntimeError('Search returned an unsuccessful HTTP response')

    if isinstance(expected, tuple):
        expect(page.get_by_role('heading', name='Member Details', exact=True)).to_be_visible()
        values = {}
        for label, value in zip(LABELS, expected):
            # Match the visible definition label, then read its associated value.
            term = page.locator('dt').filter(has_text=re.compile(rf'^{re.escape(label)}$'))
            expect(term).to_be_visible()
            definition = term.locator('xpath=following-sibling::dd[1]')
            expect(definition).to_be_visible()
            expect(definition).to_have_text(value)
            values[label] = definition.inner_text().strip()
        result = f"{values['Member Name']} | {values['Status']} | {values['Current Savings Balance']}"
    elif member_id == '99999':
        expect(page.get_by_role('heading', name='Member Not Found', exact=True)).to_be_visible()
        expect(page.get_by_text(expected, exact=True)).to_be_visible()
        result = 'MEMBER_NOT_FOUND (expected business outcome)'
    else:
        expect(page.get_by_role('alert')).to_have_text(expected)
        expect(textbox).to_be_visible()
        expect(textbox).to_have_attribute('aria-invalid', 'true')
        return 'VALIDATION_ERROR (expected): ' + expected

    page.get_by_role('link', name='Back to Search', exact=True).click()
    expect(page.get_by_role('heading', name='Member Service Portal', exact=True)).to_be_visible()
    expect(textbox).to_be_visible()
    expect(textbox).to_have_value('')
    return result + ' | Back to Search passed'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--headed', action='store_true', help='Show the browser window')
    parser.add_argument('--timeout-ms', type=int, default=10000)
    parser.add_argument('--slow-mo', type=int, default=0, metavar='MS',
                        help='Delay browser actions by this many milliseconds (use with --headed)')
    args = parser.parse_args()
    if args.timeout_ms <= 0:
        parser.error('--timeout-ms must be positive')
    if args.slow_mo < 0:
        parser.error('--slow-mo must be zero or positive')
    failures = 0
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
            try:
                for member_id, expected in CASES:
                    context = browser.new_context()
                    try:
                        page = context.new_page()
                        page.set_default_timeout(args.timeout_ms)
                        expect.set_options(timeout=args.timeout_ms)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('response', lambda response: errors.append(
                            f'HTTP {response.status}: {response.url}'
                        ) if response.status >= 400 else None)
                        result = check_case(page, args.base_url, member_id, expected)
                        if errors:
                            raise RuntimeError('; '.join(errors))
                        print(f"PASS {member_id or '(empty)'}: {result}")
                    except Exception as error:
                        failures += 1
                        print(f"FAIL {member_id or '(empty)'}: {error}", file=sys.stderr)
                    finally:
                        context.close()
            finally:
                browser.close()
    except Exception as error:
        print(f'SETUP ERROR: {error}', file=sys.stderr)
        print('Start the portal and install Playwright/Chromium as documented in README.md.', file=sys.stderr)
        return 1
    print(f'\nResults: {len(CASES) - failures}/{len(CASES)} passed; {failures} failed.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
