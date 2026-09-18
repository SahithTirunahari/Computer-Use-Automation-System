"""Read only the live rendered browser; never import the app's data."""
import base64
from dataclasses import dataclass


@dataclass
class Observation:
    url: str
    accessible_page: str
    visible_text: str
    screenshot_base64: str

    def for_model(self) -> dict:
        return {'url': self.url, 'accessible_page': self.accessible_page, 'visible_text': self.visible_text}


async def observe(page) -> Observation:
    await page.wait_for_load_state('domcontentloaded')
    body = page.locator('body')
    tree = await body.aria_snapshot()
    text = await body.inner_text()
    screenshot = await page.screenshot(type='png', animations='disabled')
    return Observation(page.url, tree[:16000], text[:12000], base64.b64encode(screenshot).decode('ascii'))


async def safe_snapshot(page) -> dict:
    """Persist structure only: omit ALL field values, free text, URLs and images.

    This is a deliberately narrow sanitized DOM snapshot for our known portal,
    not a general-purpose PII redactor for arbitrary applications.
    """
    known = {
        'heading': ['Member Service Portal', 'Find a member', 'Member Details',
                    'Member Information', 'Savings Account', 'Member Not Found'],
        'textbox': ['Member ID'], 'button': ['Search'],
        'link': ['Back to Search', 'Member Service Portal'],
    }
    controls = []
    for role, names in known.items():
        for name in names:
            locator = page.get_by_role(role, name=name, exact=True)
            count = await locator.count()
            visible = sum([await locator.nth(i).is_visible() for i in range(count)])
            if visible:
                controls.append({'role': role, 'name': name, 'visible_matches': visible})
    return {'format': 'sanitized-dom-summary-v1', 'controls': controls,
            'definition_count': await page.locator('dt').count(),
            'alert_count': await page.get_by_role('alert').count(),
            'sensitive_content': 'omitted'}
