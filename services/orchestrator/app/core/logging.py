"""Process-wide logging setup.

TODO(phase-6): structured JSON logs with correlation ids, exported via OpenTelemetry.
"""

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
