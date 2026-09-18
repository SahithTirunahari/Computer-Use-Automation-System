"""Explicit read-only portal policy; independent of prompts and model output."""
from urllib.parse import urlsplit, parse_qs
from pydantic import Field
from .actions import StrictModel, RoleTarget, DefinitionTarget


class PolicyError(RuntimeError):
    pass


class Policy(StrictModel):
    allowed_origins: list[str] = Field(default_factory=lambda: ['http://localhost:8000', 'http://127.0.0.1:8000'])
    allowed_paths: list[str] = Field(default_factory=lambda: ['/', '/member', '/static/styles.css'])
    allowed_actions: list[str] = Field(default_factory=lambda: ['click', 'type', 'keypress', 'scroll', 'extract', 'wait', 'done'])

    def check_url(self, url: str) -> None:
        parsed = urlsplit(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if (parsed.username or parsed.password or parsed.scheme not in ('http', 'https')
                or origin not in self.allowed_origins or parsed.path not in self.allowed_paths
                or parsed.fragment):
            raise PolicyError('URL is outside the configured portal allowlist')
        query = parse_qs(parsed.query, keep_blank_values=True)
        if any(key != 'member_id' for key in query) or any(len(v) != 1 for v in query.values()):
            raise PolicyError('Unexpected query parameters')

    def check_action(self, action, member_id: str) -> None:
        if action.action not in self.allowed_actions:
            raise PolicyError('Action type is not allowed')
        target = getattr(action, 'target', None)
        permitted = {
            ('textbox', 'Member ID'), ('button', 'Search'),
            ('link', 'Back to Search'), ('link', 'Member Service Portal'),
            ('heading', 'Member Details'), ('heading', 'Member Not Found'),
            ('heading', 'Member Service Portal'), ('heading', 'Savings Account'),
            ('heading', 'Member Information'), ('heading', 'Find a member'),
        }
        if isinstance(target, RoleTarget) and (target.role, target.name) not in permitted:
            raise PolicyError('Target is not an approved portal control')
        if action.action in ('click', 'keypress'):
            if (target.role, target.name) not in {
                ('button', 'Search'), ('link', 'Back to Search'),
                ('link', 'Member Service Portal'), ('textbox', 'Member ID'),
            }:
                raise PolicyError('Only read-only lookup controls may be activated')
        if action.action == 'type':
            if (target.role, target.name) != ('textbox', 'Member ID') or action.value != member_id:
                raise PolicyError('Only the requested member ID may be typed into Member ID')
        if action.action == 'extract':
            expected = {'member_id': 'Member ID', 'savings_balance': 'Current Savings Balance'}
            if not isinstance(target, DefinitionTarget) or target.label != expected[action.output_name]:
                raise PolicyError('Output must be extracted from its declared visible label')
