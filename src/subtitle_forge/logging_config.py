from __future__ import annotations

import logging
import sys

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _install_trace_method() -> None:
    def _trace(self: logging.Logger, message: str, *args: object) -> None:
        if self.isEnabledFor(TRACE):
            self._log(TRACE, message, args)

    logging.Logger.trace = _trace  # type: ignore[attr-defined]


_install_trace_method()

_SUBTITLE_FORGE_LOGGER_NAME = "subtitle_forge"
_FORMATTER = logging.Formatter("[%(levelname)-5s][%(name)s] %(message)s")

_configured = False


def configure_logging(verbose: bool = False) -> None:
    global _configured

    if _configured:
        return

    logger = logging.getLogger(_SUBTITLE_FORGE_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(TRACE if verbose else logging.WARNING)
    handler.setFormatter(_FORMATTER)

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    if name is None or name == "__main__":
        return logging.getLogger(_SUBTITLE_FORGE_LOGGER_NAME)

    child_name = f"{_SUBTITLE_FORGE_LOGGER_NAME}.{name}"
    return logging.getLogger(child_name)
