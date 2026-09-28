"""Process-wide structured logging.

structlog and the standard library both render one JSON object per line on
stderr. Every event passes the Redactor after exception formatting, so secrets
in messages, fields and stack traces are removed before anything is written.
The correlation id bound by the request middleware is merged into each event.

TODO(phase-6): export via OpenTelemetry.
"""

import logging

import structlog

from app.core.redaction import Redactor, redact_event_dict


def configure_logging(level: str, redactor: Redactor) -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        redact_event_dict(redactor),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
