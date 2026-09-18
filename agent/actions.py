"""Typed model actions. No model-provided code or selectors are accepted."""
from typing import Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class RoleTarget(StrictModel):
    kind: Literal['role']
    role: Literal['textbox', 'button', 'link', 'heading', 'alert']
    name: str = Field(min_length=1, max_length=100)


class DefinitionTarget(StrictModel):
    kind: Literal['definition']
    label: Literal['Member ID', 'Member Name', 'Status', 'Account Number', 'Current Savings Balance']


Target = Union[RoleTarget, DefinitionTarget]


class ActionBase(StrictModel):
    reason: str = Field(min_length=1, max_length=240)


class Click(ActionBase):
    action: Literal['click']
    target: RoleTarget


class Type(ActionBase):
    action: Literal['type']
    target: RoleTarget
    value: str = Field(max_length=32)


class Keypress(ActionBase):
    action: Literal['keypress']
    target: RoleTarget
    key: Literal['Enter', 'Tab', 'Escape']


class Scroll(ActionBase):
    action: Literal['scroll']
    direction: Literal['up', 'down']
    pixels: int = Field(ge=1, le=800)


class Extract(ActionBase):
    action: Literal['extract']
    target: DefinitionTarget
    output_name: Literal['member_id', 'savings_balance']


class Wait(ActionBase):
    action: Literal['wait']
    target: Target
    condition: Literal['visible']


class Success(StrictModel):
    status: Literal['success']
    output_keys: list[Literal['member_id', 'savings_balance']] = Field(min_length=2, max_length=2)


class BusinessOutcome(StrictModel):
    status: Literal['business_outcome']
    code: Literal['MEMBER_NOT_FOUND']


class Failure(StrictModel):
    status: Literal['failure']
    code: Literal['UNABLE_TO_COMPLETE']


class Done(ActionBase):
    action: Literal['done']
    result: Union[Success, BusinessOutcome, Failure]


Action = Union[Click, Type, Keypress, Scroll, Extract, Wait, Done]


class Decision(StrictModel):
    # A top-level object with a nested union works with Structured Outputs.
    next_action: Action


class RunResult(StrictModel):
    status: Literal['success', 'business_outcome', 'failure']
    code: str
    outputs: dict[str, str] = Field(default_factory=dict)
    step: int = 0
    expected: str = ''
    observed: str = ''
