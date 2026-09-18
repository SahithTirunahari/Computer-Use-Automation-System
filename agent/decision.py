"""Model integration isolated from browser execution."""
import json
from .actions import Decision
from .prompts import SYSTEM_PROMPT


class DecisionError(RuntimeError):
    pass


class OpenAIDecider:
    def __init__(self, model: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(max_retries=0)
        self.model = model
        self.last_metadata = {}

    async def decide(self, goal, observation, recent_steps, extracted_values, timeout):
        payload = {'goal': goal, 'observation': observation.for_model(),
                   'recent_steps': recent_steps[-6:], 'extracted_values': extracted_values}
        response = await self.client.responses.parse(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=[{'role': 'user', 'content': [
                {'type': 'input_text', 'text': json.dumps(payload)},
                {'type': 'input_image', 'image_url': 'data:image/png;base64,' + observation.screenshot_base64},
            ]}],
            text_format=Decision, store=False, max_output_tokens=1600,
            timeout=min(timeout, 45.0),
        )
        self.last_metadata = {'response_id': response.id,
                              'usage': response.usage.model_dump() if response.usage else {}}
        if response.output_parsed is None:
            raise DecisionError('MODEL_REFUSED_OR_INCOMPLETE')
        return response.output_parsed

    async def close(self):
        await self.client.close()
