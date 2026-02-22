import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from gemini_webapi.api import app, get_gemini_client


class TestGenerateContentApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = {}

    def test_generate_content_response_shape_matches_gemini(self):
        fake_output = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    text="ok",
                    images=[SimpleNamespace(url="https://example.com/fake-image.png")],
                )
            ]
        )

        fake_gemini_client = SimpleNamespace(
            cookies={},
            generate_content=AsyncMock(return_value=fake_output),
        )

        async def override_client():
            return fake_gemini_client

        app.dependency_overrides[get_gemini_client] = override_client

        with patch(
            "gemini_webapi.api._fetch_inline_data",
            new=AsyncMock(return_value=("image/png", base64.b64encode(b"img").decode())),
        ):
            resp = self.client.post(
                "/v1beta/models/gemini-3.0-pro:generateContent",
                headers={"x-goog-api-key": "dummy"},
                json={
                    "contents": [{"parts": [{"text": "Generate an image of a cat"}]}],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                        "imageConfig": {"aspectRatio": "16:9"},
                    },
                },
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("candidates", data)
        self.assertEqual(data["modelVersion"], "gemini-3.0-pro")
        self.assertEqual(data["candidates"][0]["content"]["role"], "model")
        self.assertEqual(data["candidates"][0]["content"]["parts"][0]["text"], "ok")
        self.assertIn("inlineData", data["candidates"][0]["content"]["parts"][1])

    def test_inline_reference_keeps_image_extension_for_upload(self):
        fake_output = SimpleNamespace(
            candidates=[SimpleNamespace(text="ok", images=[])]
        )
        fake_gemini_client = SimpleNamespace(
            cookies={},
            generate_content=AsyncMock(return_value=fake_output),
        )

        async def override_client():
            return fake_gemini_client

        app.dependency_overrides[get_gemini_client] = override_client

        img_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
        resp = self.client.post(
            "/v1beta/models/gemini-3.0-pro:generateContent",
            headers={"x-goog-api-key": "dummy"},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": "Use this reference image"},
                            {"inlineData": {"mimeType": "image/png", "data": img_b64}},
                        ]
                    }
                ]
            },
        )
        self.assertEqual(resp.status_code, 200)

        kwargs = fake_gemini_client.generate_content.await_args.kwargs
        files = kwargs["files"]
        self.assertTrue(files)
        self.assertTrue(files[0].name.endswith(".png"))
