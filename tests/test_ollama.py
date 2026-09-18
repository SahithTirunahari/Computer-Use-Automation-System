import json
import unittest
from unittest.mock import AsyncMock
import httpx
from agent.ollama import OllamaDecider, OllamaError
from agent.observer import Observation
from agent.decision import DecisionError
from pydantic import ValidationError


class OllamaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.decider = OllamaDecider()
        self.observation = Observation('http://localhost:8000/', 'textbox Member ID', 'Member ID', 'aW1hZ2U=')

    async def asyncTearDown(self):
        await self.decider.close()

    async def test_schema_and_image_request(self):
        action = {'next_action': {'action': 'type', 'reason': 'Enter requested ID',
                  'target': {'kind': 'role', 'role': 'textbox', 'name': 'Member ID'}, 'value': '12345'}}
        self.decider.client.post = AsyncMock(return_value=httpx.Response(200, json={
            'message': {'content': json.dumps(action)}, 'done': True, 'eval_count': 40}))
        result = await self.decider.decide('goal', self.observation, [], {}, 300)
        self.assertEqual(result.next_action.value, '12345')
        args = self.decider.client.post.call_args.kwargs
        self.assertEqual(args['timeout'], 120)
        self.assertEqual(args['json']['messages'][1]['images'], ['aW1hZ2U='])
        self.assertEqual(args['json']['format']['type'], 'object')
        self.assertFalse(args['json']['stream'])

    async def test_missing_model(self):
        self.decider.client.post = AsyncMock(return_value=httpx.Response(404))
        with self.assertRaisesRegex(OllamaError, 'MODEL_NOT_FOUND'):
            await self.decider.decide('goal', self.observation, [], {}, 10)

    async def test_invalid_model_action(self):
        self.decider.client.post = AsyncMock(return_value=httpx.Response(200, json={'message': {'content': '{"code":"unsafe"}'}}))
        with self.assertRaises(ValidationError):
            await self.decider.decide('goal', self.observation, [], {}, 10)

    async def test_truncated_response(self):
        self.decider.client.post = AsyncMock(return_value=httpx.Response(200, json={'done_reason': 'length', 'message': {'content': '{}'}}))
        with self.assertRaisesRegex(DecisionError, 'TRUNCATED'):
            await self.decider.decide('goal', self.observation, [], {}, 10)

    async def test_local_endpoint_only(self):
        with self.assertRaises(ValueError):
            OllamaDecider(base_url='https://example.com')
