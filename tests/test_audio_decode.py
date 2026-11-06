"""Exercise the real decoder without downloading a speech model."""
import importlib.util
import tempfile
import unittest
import wave
from pathlib import Path


@unittest.skipUnless(importlib.util.find_spec('faster_whisper'), 'Requires the app dependencies')
class AudioDecode(unittest.TestCase):
    def test_transcription_decoder_accepts_local_audio(self):
        from faster_whisper.audio import decode_audio

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'silence.wav'
            with wave.open(str(audio), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16000)
                output.writeframes(b'\x00\x00' * 16000)
            samples = decode_audio(str(audio), sampling_rate=16000)
            self.assertEqual(samples.shape, (16000,))
            self.assertEqual(float(abs(samples).max()), 0)
