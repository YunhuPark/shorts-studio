"""Gemini API text generation over REST (stdlib only): turns a prompt into one JSON object. Credentials: GEMINI_API_KEY.

The model id is a parameter because model names change; an unknown id fails with the API's own error text.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import ProviderError

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiStoryProvider:
    def __init__(self, model: str, api_key: str | None = None, timeout: int = 90):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.timeout = timeout

    @staticmethod
    def build_request(system: str, prompt: str, schema: dict) -> dict:
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                                     "temperature": 0.9}}

    def generate(self, system: str, prompt: str, schema: dict) -> dict:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY must be set")
        body = json.dumps(self.build_request(system, prompt, schema)).encode("utf-8")
        req = urllib.request.Request(ENDPOINT.format(model=self.model), data=body,
                                     headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            raise ProviderError(f"Gemini text request failed: HTTP {e.code} {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ProviderError(f"Gemini text request failed: {e}") from e
        for cand in payload.get("candidates", []):
            text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            if text.strip():
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    raise ProviderError("Gemini returned text that is not valid JSON") from e
                if not isinstance(data, dict):
                    raise ProviderError("Gemini returned JSON that is not an object")
                return data
        reason = (payload.get("promptFeedback") or {}).get("blockReason")
        raise ProviderError(f"Gemini returned no story{f' (blocked: {reason})' if reason else ''}")
