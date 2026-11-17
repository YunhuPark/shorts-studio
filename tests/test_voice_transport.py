import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_studio.models import VoiceSpec
from shorts_studio.providers.base import ProviderError
from shorts_studio.providers.voice_azure import AzureVoiceProvider

SPEC = VoiceSpec("azure", "ko-KR-InJoonNeural", "0%", "0%")

class VoiceTransportTests(unittest.TestCase):
    def test_provider_transport_has_finite_timeout_and_bounded_read(self):
        seen = {}
        class Response(io.BytesIO):
            def read(self, size=-1):
                seen['size'] = size
                return super().read(size)
        def transport(request, **kwargs):
            seen.update(kwargs)
            return Response(b'synthetic-wav')
        with tempfile.TemporaryDirectory() as root, patch('urllib.request.urlopen', transport):
            result=AzureVoiceProvider(root, 'synthetic-key', 'synthetic-region').synthesize('hello',SPEC)
            self.assertEqual(result.read_bytes(), b'synthetic-wav')
        self.assertGreater(seen.get('timeout',0),0)
        self.assertLessEqual(seen['timeout'],30)
        self.assertGreater(seen['size'],0)
        self.assertLessEqual(seen['size'],8*1024*1024+1)

    def test_oversized_audio_is_not_published_as_a_cache_hit(self):
        with tempfile.TemporaryDirectory() as root, patch('urllib.request.urlopen', return_value=io.BytesIO(b'x'*(8*1024*1024+1))):
            with self.assertRaises(ProviderError):
                AzureVoiceProvider(root,'synthetic-key','synthetic-region').synthesize('hello',SPEC)
            self.assertEqual(list(Path(root).glob('*.wav')),[])
