"""Azure AI Speech text-to-speech. Credentials come from AZURE_SPEECH_KEY / AZURE_SPEECH_REGION."""
from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

from ..models import VoiceSpec
from .base import ProviderError


class AzureVoiceProvider:
    def __init__(self, cache_dir: str | Path, key: str | None = None, region: str | None = None):
        self.cache_dir = Path(cache_dir)
        self.key = key or os.environ.get("AZURE_SPEECH_KEY")
        self.region = region or os.environ.get("AZURE_SPEECH_REGION")

    @staticmethod
    def cache_key(text: str, spec: VoiceSpec) -> str:
        # same key scheme as the prototype, so its cached audio is reused (no repeat character charge)
        raw = f"{spec.voice}|{spec.rate}|{spec.pitch}|{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def synthesize(self, text: str, spec: VoiceSpec) -> Path:
        path = self.cache_dir / (self.cache_key(text, spec) + ".wav")
        if path.exists():
            return path
        if not (self.key and self.region):
            raise ProviderError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        prosody = f"<prosody rate='{spec.rate}' pitch='{spec.pitch}'>{escape(text)}</prosody>"
        ssml = f"<speak version='1.0' xml:lang='ko-KR'><voice name='{spec.voice}'>{prosody}</voice></speak>"
        req = urllib.request.Request(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1",
            data=ssml.encode("utf-8"),
            headers={"Ocp-Apim-Subscription-Key": self.key,
                     "Content-Type": "application/ssml+xml",
                     "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                     "User-Agent": "shorts-studio"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ProviderError("Azure TTS response exceeds the 8 MiB audio limit")
        except urllib.error.HTTPError as e:
            raise ProviderError(f"Azure TTS failed: HTTP {e.code}") from e
        path.write_bytes(data)
        return path
