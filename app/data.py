"""Fake demonstration data only; amounts are stored as integer cents."""

from typing import TypedDict


class Member(TypedDict):
    name: str
    account_number: str
    balance_cents: int
    status: str


MEMBERS: dict[str, Member] = {
    "12345": {
        "name": "Alice Johnson",
        "account_number": "SAV-1001",
        "balance_cents": 423112,
        "status": "Active",
    },
    "54321": {
        "name": "Bob Smith",
        "account_number": "SAV-2002",
        "balance_cents": 85050,
        "status": "Active",
    },
    "77777": {
        "name": "Carol Williams",
        "account_number": "SAV-3003",
        "balance_cents": 1245000,
        "status": "Restricted",
    },
}
