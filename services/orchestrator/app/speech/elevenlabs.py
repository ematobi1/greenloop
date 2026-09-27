"""ElevenLabs implementation of SpeechProvider."""

from pydantic import SecretStr


class ElevenLabsSpeechProvider:
    name = "elevenlabs"

    def __init__(self, api_key: SecretStr, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def transcribe(self, audio: bytes, mime_type: str) -> str:
        raise NotImplementedError("TODO(phase-5): speech-to-text")

    async def synthesize(self, text: str, voice_id: str) -> bytes:
        raise NotImplementedError("TODO(phase-5): text-to-speech")
