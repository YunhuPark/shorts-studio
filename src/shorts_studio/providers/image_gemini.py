"""Gemini API image generation over REST (stdlib only). Credentials: GEMINI_API_KEY.

Phase 0 harness: the model id is a parameter because model names change; an unknown id fails with the
API's own error text. Reference images are sent as inline data next to the prompt.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import ProviderError

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiImageProvider:
    def __init__(self, model: str, api_key: str | None = None, aspect_ratio: str = "9:16"):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.aspect_ratio = aspect_ratio

    def build_request(self, prompt: str, refs: list[Path]) -> dict:
        parts: list[dict] = [{"text": prompt}]
        for ref in refs:
            mime = mimetypes.guess_type(ref.name)[0] or "image/png"
            parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(ref.read_bytes()).decode()}})
        return {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"],
                                     "imageConfig": {"aspectRatio": self.aspect_ratio}}}

    def generate(self, prompt: str, refs: list[Path], out_path: Path) -> Path:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY must be set")
        body = json.dumps(self.build_request(prompt, refs)).encode("utf-8")
        req = urllib.request.Request(ENDPOINT.format(model=self.model), data=body,
                                     headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:600]
            raise ProviderError(f"Gemini image request failed: HTTP {e.code} {detail}") from e
        for cand in payload.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                blob = part.get("inlineData") or part.get("inline_data")
                if blob and blob.get("data"):
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(base64.b64decode(blob["data"]))
                    return out_path
        raise ProviderError("Gemini returned no image: " + json.dumps(payload)[:600])
