import base64
import io
import unittest
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from app.image_support import MAX_IMAGE_BYTES, prepare_image
from scripts import llm_router


class ImageValidationTests(unittest.TestCase):
    def test_normalizes_and_resizes_image(self):
        source = io.BytesIO()
        Image.new('RGBA', (3000, 1500)).save(source, format='PNG')
        encoded = prepare_image(source.getvalue())
        with Image.open(io.BytesIO(base64.b64decode(encoded))) as result:
            self.assertEqual(result.size, (2048, 1024))
            self.assertEqual(result.format, 'PNG')
            self.assertEqual(result.mode, 'RGB')

    def test_rejects_invalid_bytes(self):
        with self.assertRaises(ValueError):
            prepare_image(b'not an image')

    def test_rejects_oversize_upload(self):
        with self.assertRaises(ValueError):
            prepare_image(b'x' * (MAX_IMAGE_BYTES + 1))

    def test_rejects_unsupported_format(self):
        source = io.BytesIO()
        Image.new('RGB', (10, 10)).save(source, format='GIF')
        with self.assertRaises(ValueError):
            prepare_image(source.getvalue())

    def test_rejects_excessive_dimensions(self):
        source = io.BytesIO()
        Image.new('RGB', (100, 100)).save(source, format='PNG')
        with patch('app.image_support.MAX_IMAGE_PIXELS', 100):
            with self.assertRaises(ValueError):
                prepare_image(source.getvalue())


class VisionRoutingTests(unittest.TestCase):
    def test_sends_image_to_ollama(self):
        response = Mock()
        response.json.return_value = {'message': {'content': 'Check your network.'}}
        with patch.object(llm_router._http_client, 'post', return_value=response) as post:
            answer = llm_router.ask_image('Why this error?', 'encoded-image')
        self.assertEqual(answer, 'Check your network.')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['messages'][0]['images'], ['encoded-image'])
        self.assertIn('Why this error?', payload['messages'][0]['content'])

    def test_gemini_fallback_keeps_image(self):
        response = Mock()
        response.json.return_value = {'candidates': [{'content': {'parts': [{'text': 'Try restarting.'}]}}]}
        with (
            patch.object(llm_router._http_client, 'post', side_effect=[httpx.ConnectError('offline'), response]) as post,
            patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key'}),
            patch.object(llm_router.settings, 'GEMINI_FALLBACK_ENABLED', True),
        ):
            self.assertEqual(llm_router.ask_image('Help', 'image-data'), 'Try restarting.')
        parts = post.call_args.kwargs['json']['contents'][0]['parts']
        self.assertEqual(parts[1]['inline_data']['data'], 'image-data')

    def test_failure_does_not_use_text_only_model(self):
        with (
            patch.object(llm_router._http_client, 'post', side_effect=httpx.ConnectError('offline')),
            patch.object(llm_router.settings, 'GEMINI_FALLBACK_ENABLED', False),
            patch.object(llm_router, 'ask_llm') as text_model,
        ):
            with self.assertRaises(RuntimeError):
                llm_router.ask_image('Help', 'image-data')
            text_model.assert_not_called()


class ImageEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.auth import get_current_user
        from app.database import get_db
        cls.app = app
        cls.get_current_user = staticmethod(get_current_user)
        cls.get_db = staticmethod(get_db)
        cls.client = TestClient(app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

    def authenticated(self):
        self.db = Mock()
        self.app.dependency_overrides[self.get_current_user] = lambda: {'username': 'employee', 'role': 'employee'}
        self.app.dependency_overrides[self.get_db] = lambda: self.db

    def test_requires_login(self):
        response = self.client.post('/query/image', files={'image': ('error.png', b'bad', 'image/png')})
        self.assertEqual(response.status_code, 401)

    def test_invalid_image_never_calls_model(self):
        self.authenticated()
        with patch.object(llm_router, 'ask_image') as model:
            response = self.client.post('/query/image', files={'image': ('error.png', b'bad', 'image/png')})
        self.assertEqual(response.status_code, 400)
        model.assert_not_called()

    def test_rejects_other_users_conversation(self):
        self.authenticated()
        self.db.query.return_value.filter.return_value.first.return_value = None
        response = self.client.post('/query/image', data={'session_id': '7'}, files={'image': ('error.png', b'bad', 'image/png')})
        self.assertEqual(response.status_code, 404)

    def test_valid_multipart_upload(self):
        self.authenticated()
        source = io.BytesIO()
        Image.new('RGB', (10, 10)).save(source, format='PNG')
        with (
            patch.object(llm_router, 'ask_image', return_value='Check the connection.') as model,
            patch('app.main.log_action'),
        ):
            response = self.client.post('/query/image', data={'question': 'Why this error?'}, files={'image': ('error.png', source.getvalue(), 'image/png')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'image_troubleshooting')
        self.assertEqual(model.call_args.args[0], 'Why this error?')
        self.assertTrue(model.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
