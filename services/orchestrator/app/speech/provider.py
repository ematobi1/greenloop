"""SpeechProvider: the voice interface. Vendors implement it; the orchestrator uses only this."""

from typing import Protocol


class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes, mime_type: str) -> str: ...

    async def synthesize(self, text: str, voice_id: str) -> bytes: ...
