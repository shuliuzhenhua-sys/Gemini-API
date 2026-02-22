import asyncio
import base64
import io
import mimetypes
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict, Field

from .client import GeminiClient
from .types.image import GeneratedImage


class InlineDataInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mime_type: str | None = Field(default=None, alias="mimeType")
    data: str


class PartInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str | None = None
    inline_data: InlineDataInput | None = Field(default=None, alias="inlineData")


class ContentInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    role: str | None = None
    parts: list[PartInput]


class ImageConfigInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    aspect_ratio: str | None = Field(default=None, alias="aspectRatio")


class GenerationConfigInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    response_modalities: list[str] | None = Field(default=None, alias="responseModalities")
    image_config: ImageConfigInput | None = Field(default=None, alias="imageConfig")


class GenerateContentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contents: list[ContentInput]
    generationConfig: GenerationConfigInput | None = None
    safetySettings: list[dict[str, Any]] | None = None


app = FastAPI(title="Gemini WebAPI Compatibility Layer", version="0.1.0")

_client_lock = asyncio.Lock()
_client: GeminiClient | None = None


async def _get_or_init_client() -> GeminiClient:
    global _client
    async with _client_lock:
        if _client is not None and _client._running:
            return _client

        secure_1psid = os.getenv("SECURE_1PSID")
        secure_1psidts = os.getenv("SECURE_1PSIDTS")
        _client = GeminiClient(secure_1psid, secure_1psidts, verify=False)
        await _client.init(
            timeout=float(os.getenv("GEMINI_API_TIMEOUT", "120")),
            auto_refresh=False,
            verbose=False,
            watchdog_timeout=float(os.getenv("GEMINI_WATCHDOG_TIMEOUT", "120")),
        )
        return _client


async def get_gemini_client() -> GeminiClient:
    return await _get_or_init_client()


async def _fetch_inline_data(image: Any, cookies: Any) -> tuple[str, str]:
    image_url = image.url
    # Gemini generated-image URLs are usually previews; request full-size variant.
    if isinstance(image, GeneratedImage) and "=s" not in image_url:
        image_url = f"{image_url}=s2048"

    async with AsyncClient(
        http2=True, follow_redirects=True, cookies=cookies, timeout=120
    ) as http_client:
        response = await http_client.get(image_url)
        response.raise_for_status()
        mime = response.headers.get("content-type", "image/png").split(";")[0]
        return mime, base64.b64encode(response.content).decode("utf-8")


def _extract_prompt_and_files(
    contents: list[ContentInput],
) -> tuple[str, list[io.BytesIO]]:
    prompt_parts: list[str] = []
    files: list[io.BytesIO] = []

    file_idx = 0
    for content in contents:
        for part in content.parts:
            if part.text:
                prompt_parts.append(part.text)
            if part.inline_data:
                try:
                    raw = base64.b64decode(part.inline_data.data)
                except Exception as exc:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid inlineData base64: {exc}"
                    ) from exc
                mime = part.inline_data.mime_type or "application/octet-stream"
                ext = mimetypes.guess_extension(mime) or ".bin"
                fileobj = io.BytesIO(raw)
                fileobj.name = f"inline_ref_{file_idx}{ext}"
                files.append(fileobj)
                file_idx += 1

    prompt = "\n".join(prompt_parts).strip()
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="At least one text part is required in contents.parts.text.",
        )

    return prompt, files


@app.post("/v1beta/models/{model}:generateContent")
async def generate_content(
    model: str,
    body: GenerateContentRequest,
    x_goog_api_key: str | None = Header(default=None, alias="x-goog-api-key"),
    client: GeminiClient = Depends(get_gemini_client),
) -> dict[str, Any]:
    # Keep the header for protocol compatibility; current backend uses cookie auth.
    _ = x_goog_api_key

    prompt, files = _extract_prompt_and_files(body.contents)

    try:
        output = await client.generate_content(
            prompt=prompt,
            files=files or None,
            model=model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported model: {model}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gemini request failed: {exc}") from exc

    candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(output.candidates):
        parts: list[dict[str, Any]] = []
        if candidate.text:
            parts.append({"text": candidate.text})

        for image in candidate.images:
            mime_type, b64_data = await _fetch_inline_data(image, client.cookies)
            parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})

        candidates.append(
            {
                "index": index,
                "content": {"role": "model", "parts": parts},
                "finishReason": "STOP",
            }
        )

    return {
        "candidates": candidates,
        "modelVersion": model,
    }


@app.on_event("shutdown")
async def _shutdown_client() -> None:
    global _client
    if _client:
        await _client.close()
    _client = None
