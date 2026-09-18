"""Version 1 is deliberately restricted to the read-only savings lookup flow."""
from typing import Literal, Union
from pydantic import Field, model_validator
from agent.actions import StrictModel, RoleTarget, DefinitionTarget


class InputRef(StrictModel):
    input: Literal['member_id']


class InputContract(StrictModel):
    type: Literal['string'] = 'string'
    pattern: Literal['^[0-9]{5}$'] = '^[0-9]{5}$'
    required: Literal[True] = True


class OutputContract(StrictModel):
    type: Literal['string'] = 'string'
    source: DefinitionTarget
    pattern: str


class TypeStep(StrictModel):
    id: str
    action: Literal['type']
    target: RoleTarget
    value: InputRef


class ClickStep(StrictModel):
    id: str
    action: Literal['click']
    target: RoleTarget


class KeyStep(StrictModel):
    id: str
    action: Literal['keypress']
    target: RoleTarget
    key: Literal['Enter']


class ExtractStep(StrictModel):
    id: str
    action: Literal['extract']
    target: DefinitionTarget
    output_name: Literal['member_id', 'savings_balance']


class DetailsCondition(StrictModel):
    heading: Literal['Member Details'] = 'Member Details'
    member_label: Literal['Member ID'] = 'Member ID'
    equals: InputRef = Field(default_factory=lambda: InputRef(input='member_id'))
    then: Literal['continue'] = 'continue'


class MissingCondition(StrictModel):
    heading: Literal['Member Not Found'] = 'Member Not Found'
    message_template: Literal['No member exists with ID {member_id}.'] = 'No member exists with ID {member_id}.'
    member_query_parameter: Literal['member_id'] = 'member_id'
    equals: InputRef = Field(default_factory=lambda: InputRef(input='member_id'))
    then: Literal['return_business_outcome'] = 'return_business_outcome'
    code: Literal['MEMBER_NOT_FOUND'] = 'MEMBER_NOT_FOUND'


class OutcomeStep(StrictModel):
    id: str
    action: Literal['await_outcome'] = 'await_outcome'
    timeout_ms: int = Field(default=10000, ge=1, le=30000)
    details: DetailsCondition = Field(default_factory=DetailsCondition)
    not_found: MissingCondition = Field(default_factory=MissingCondition)
    on_timeout: Literal['UNEXPECTED_STATE_OR_TIMEOUT'] = 'UNEXPECTED_STATE_OR_TIMEOUT'
    on_ambiguous: Literal['AMBIGUOUS_OUTCOME'] = 'AMBIGUOUS_OUTCOME'


Step = Union[TypeStep, ClickStep, KeyStep, OutcomeStep, ExtractStep]
BALANCE_PATTERN = r'^\$\d{1,3}(?:,\d{3})*\.\d{2}$'


class SuccessContract(StrictModel):
    heading: Literal['Member Details'] = 'Member Details'
    identity_output: Literal['member_id'] = 'member_id'
    equals: InputRef = Field(default_factory=lambda: InputRef(input='member_id'))
    required_outputs: list[str] = Field(default_factory=lambda: ['member_id', 'savings_balance'])
    recheck_outputs_against_live_ui: Literal[True] = True
    status: Literal['success'] = 'success'
    code: Literal['GOAL_VERIFIED'] = 'GOAL_VERIFIED'


class SourceRun(StrictModel):
    run_id: str = Field(pattern=r'^discovery-[a-f0-9]{12}$')
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    outcome: Literal['GOAL_VERIFIED', 'MEMBER_NOT_FOUND']
    binding: Literal['recorded_input_reference', 'legacy_enforced_policy_migration']


class Provenance(StrictModel):
    compiler: Literal['portal-lookup-v1'] = 'portal-lookup-v1'
    successful_run: SourceRun
    not_found_run: SourceRun
    outcome_rule_source: Literal['portal-v1-reviewed-rule-backed-by-not-found-run'] = 'portal-v1-reviewed-rule-backed-by-not-found-run'


class Capability(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    name: Literal['get_savings_balance'] = 'get_savings_balance'
    capability_version: Literal['1.0.0'] = '1.0.0'
    surface: Literal['member-service-portal-web-v1'] = 'member-service-portal-web-v1'
    entry_path: Literal['/'] = '/'
    policy: Literal['read-only-member-lookup-v1'] = 'read-only-member-lookup-v1'
    target_resolution: Literal['exactly-one-visible-match; no positional fallback'] = 'exactly-one-visible-match; no positional fallback'
    inputs: dict[str, InputContract]
    outputs: dict[str, OutputContract]
    steps: list[Step]
    success: SuccessContract = Field(default_factory=SuccessContract)
    provenance: Provenance

    @model_validator(mode='after')
    def valid_flow(self):
        if set(self.inputs) != {'member_id'} or set(self.outputs) != {'member_id', 'savings_balance'}:
            raise ValueError('Lookup requires member_id input and both declared outputs')
        expected = {'member_id': ('Member ID', '^[0-9]{5}$'),
                    'savings_balance': ('Current Savings Balance', BALANCE_PATTERN)}
        for name, (label, pattern) in expected.items():
            if self.outputs[name].source.label != label or self.outputs[name].pattern != pattern:
                raise ValueError('Output contract does not match its visible source and format')
        ids = [s.id for s in self.steps]
        if len(set(ids)) != len(ids) or any(not i or not i.isidentifier() for i in ids):
            raise ValueError('Step IDs must be unique identifiers')
        if len(self.steps) != 5:
            raise ValueError('Version 1 requires type, submit, outcome, and two extractions')
        typing, submit, outcome, *extracts = self.steps
        textbox = RoleTarget(kind='role', role='textbox', name='Member ID')
        search = RoleTarget(kind='role', role='button', name='Search')
        if not isinstance(typing, TypeStep) or typing.target != textbox:
            raise ValueError('First step must bind member_id to the Member ID textbox')
        if not ((isinstance(submit, ClickStep) and submit.target == search)
                or (isinstance(submit, KeyStep) and submit.target in (textbox, search))):
            raise ValueError('Second step must submit the lookup')
        if not isinstance(outcome, OutcomeStep):
            raise ValueError('Submission requires an explicit outcome checkpoint')
        if not all(isinstance(s, ExtractStep) for s in extracts):
            raise ValueError('Only extractions may follow the outcome checkpoint')
        if {s.output_name for s in extracts} != set(self.outputs):
            raise ValueError('Every declared output must be extracted exactly once')
        if any(s.target != self.outputs[s.output_name].source for s in extracts):
            raise ValueError('Extraction target does not match declared output')
        if sorted(self.success.required_outputs) != ['member_id', 'savings_balance']:
            raise ValueError('Success must require both outputs')
        if (self.provenance.successful_run.outcome != 'GOAL_VERIFIED'
                or self.provenance.not_found_run.outcome != 'MEMBER_NOT_FOUND'):
            raise ValueError('Both successful and not-found provenance are required')
        return self
