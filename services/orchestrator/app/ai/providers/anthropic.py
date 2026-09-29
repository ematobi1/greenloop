"""Anthropic Messages API provider (streaming).

The SDK retries connection errors, 408, 409, 429 and 5xx with backoff before any
output arrives (`max_retries`). Failures are mapped to AiError codes; the vendor
message is logged with the request id, never returned to the client. A refusal
stop reason is a failure, not an empty answer.
"""

from collections.abc import AsyncIterator

import anthropic
import structlog
from pydantic import SecretStr

from app.ai.errors import AiError
from app.ai.providers.base import Done, GenerationRequest, ProviderConfig, StreamEvent, TextDelta

logger = structlog.get_logger(__name__)


class AnthropicProvider:
    def __init__(
        self,
        config: ProviderConfig,
        api_key: SecretStr,
        effort: str,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.config = config
        self._effort = effort
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value(),
            timeout=config.timeout_seconds,
            max_retries=config.max_retries,
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        try:
            async with self._client.messages.stream(
                model=self.config.model,
                max_tokens=request.max_output_tokens,
                system=request.system,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                output_config={"effort": self._effort},
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield TextDelta(text)
                final = await stream.get_final_message()
                request_id = stream.request_id
        except anthropic.APITimeoutError as err:
            raise AiError("timeout") from err
        except anthropic.APIConnectionError as err:
            logger.warning("anthropic_connection_failed")
            raise AiError("unavailable") from err
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as err:
            _log_status("anthropic_credentials_rejected", err)
            raise AiError("not_configured") from err
        except (anthropic.RateLimitError, anthropic.InternalServerError) as err:
            _log_status("anthropic_unavailable", err)
            raise AiError("unavailable") from err
        except anthropic.APIStatusError as err:
            # 529 overloaded and other 5xx subclasses are transient, whatever their class.
            if err.status_code >= 500:
                _log_status("anthropic_unavailable", err)
                raise AiError("unavailable") from err
            _log_status("anthropic_rejected_request", err)
            raise AiError("rejected") from err

        if final.stop_reason == "refusal":
            category = getattr(final.stop_details, "category", None)
            logger.warning("anthropic_refusal", category=category, request_id=request_id)
            raise AiError("refused")
        yield Done(
            stop_reason=final.stop_reason,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            request_id=request_id,
        )


def _log_status(event: str, err: anthropic.APIStatusError) -> None:
    logger.warning(event, status=err.status_code, error_type=err.type, request_id=err.request_id)
