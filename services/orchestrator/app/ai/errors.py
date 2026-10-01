"""AI failures with messages that are always safe to show a client.

Provider details (status codes, request ids, vendor messages) are logged, never
returned. Each code maps to one HTTP status and an `AI_<CODE>` error code.
"""

from app.core.errors import ApiError

PUBLIC_MESSAGES = {
    "not_configured": "No model provider is configured.",
    "unknown_provider": "Unknown model provider.",
    "timeout": "The model provider timed out.",
    "unavailable": "The model provider is unavailable. Try again shortly.",
    "rejected": "The model provider rejected the request.",
    "refused": "The model declined to answer this request.",
    "invalid_response": "The model provider returned an invalid response.",
    "truncated": "The reply was cut off because it reached the length limit.",
    "client_disconnected": "The client disconnected before the reply finished.",
    "context_too_large": "The message is too large for the model context.",
}

HTTP_STATUS = {
    "not_configured": 503,
    "unknown_provider": 422,
    "timeout": 504,
    "unavailable": 503,
    "rejected": 502,
    "refused": 422,
    "invalid_response": 502,
    "truncated": 502,
    "client_disconnected": 400,
    "context_too_large": 422,
}


class AiError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(PUBLIC_MESSAGES[code])
        self.code = code
        self.retryable = retryable

    @property
    def public_message(self) -> str:
        return PUBLIC_MESSAGES[self.code]

    @property
    def api_code(self) -> str:
        return f"AI_{self.code.upper()}"

    def to_api_error(self) -> ApiError:
        return ApiError(HTTP_STATUS[self.code], self.api_code, self.public_message)
