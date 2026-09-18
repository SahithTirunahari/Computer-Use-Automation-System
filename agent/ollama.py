"""Local Ollama adapter: images + JSON schema, with no API key."""
import json
from urllib.parse import urlsplit
import httpx
from .actions import Decision
from .decision import DecisionError
from .prompts import SYSTEM_PROMPT


class OllamaError(RuntimeError):
    """Safe diagnostic code; never contains raw server responses."""


class OllamaDecider:
    def __init__(self, model='qwen3-vl:4b-instruct', base_url='http://localhost:11434'):
        url = urlsplit(base_url)
        if (url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1')
                or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
            raise ValueError('Ollama must use a local HTTP endpoint')
        self.client = httpx.AsyncClient(base_url=base_url.rstrip('/'), trust_env=False)
        self.model = model
        self.last_metadata = {}

    async def decide(self, goal, observation, recent_steps, extracted_values, timeout):
        self.last_metadata = {}
        schema = Decision.model_json_schema()
        payload = {'goal': goal, 'observation': observation.for_model(),
                   'recent_steps': recent_steps[-6:], 'extracted_values': extracted_values}
        try:
            response = await self.client.post('/api/chat', json={
                'model': self.model, 'stream': False,
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT + '\nJSON schema:\n' + json.dumps(schema)},
                    {'role': 'user', 'content': json.dumps(payload), 'images': [observation.screenshot_base64]},
                ],
                'format': schema,
                'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 1600},
                'keep_alive': '5m',
            }, timeout=max(0.1, min(timeout, 120.0)))
        except httpx.TimeoutException as exc:
            raise OllamaError('OLLAMA_TIMEOUT') from exc
        except httpx.RequestError as exc:
            raise OllamaError('OLLAMA_UNAVAILABLE') from exc
        if response.status_code == 404:
            raise OllamaError('OLLAMA_MODEL_NOT_FOUND')
        if response.is_error:
            raise OllamaError('OLLAMA_REQUEST_FAILED')
        try:
            body = response.json()
            content = body['message']['content']
            if body.get('done_reason') == 'length':
                raise DecisionError('MODEL_OUTPUT_TRUNCATED')
            if not isinstance(content, str) or not content.strip():
                raise DecisionError('MODEL_EMPTY_RESPONSE')
            self.last_metadata = {'provider': 'ollama', **{
                key: body[key] for key in ('prompt_eval_count', 'eval_count', 'total_duration', 'load_duration')
                if isinstance(body.get(key), int)
            }}
            return Decision.model_validate_json(content)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise DecisionError('INVALID_MODEL_RESPONSE') from exc

    async def close(self):
        await self.client.aclose()
