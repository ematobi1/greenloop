# ADR 0004: Voice behind a SpeechProvider interface

- Status: Accepted
- Date: 2026-09-27

## Context

Voice is planned for phase 5, and ElevenLabs is the first vendor. Vendors change pricing, quality and terms, and voice data is sensitive. GreenLoop must own orchestration rather than handing conversation control to a vendor's agent platform.

## Decision

The orchestrator depends only on `app/speech/provider.py`, a `SpeechProvider` protocol with `transcribe(audio, mime_type)` and `synthesize(text, voice_id)`. `app/speech/elevenlabs.py` is one implementation. The same pattern applies to models: `app/ai/providers/base.py` defines `ModelProvider`, and `anthropic.py` implements it.

## Consequences

- Swapping or adding a vendor touches one module and its tests.
- Transcribed text enters the normal chat path, so memory, permissions and approvals apply to voice exactly as to text.
- Vendor-specific features (voice cloning, conversational agents) are used only when they fit behind the interface.
- API keys are per-provider settings (`ELEVENLABS_API_KEY`, `ANTHROPIC_API_KEY`) held as `SecretStr`.
