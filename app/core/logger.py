import logging
import sys
from typing import Optional

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a named logger configured for this application."""
    return logging.getLogger(name or settings.app_name)


def setup_logging() -> None:
    """Configure root logging once at application startup."""
    level = logging.DEBUG if settings.debug else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid adding duplicate handlers on reload
    if not root_logger.handlers:
        root_logger.addHandler(handler)

    # Silence noisy third-party loggers in production
    if not settings.debug:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
