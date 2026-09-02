"""Application entrypoint.

`main.py` acts as the composition root: it loads centralized configuration,
configures logging, instantiates the process supervisor, and runs until stop.
"""

from __future__ import annotations

import logging

from src.config.center import load_config
from src.runtime.supervisor import PublisherSupervisor


def _configure_logging(level: str) -> None:
    """Configure global logging once from config center log level."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> int:
    """Load config, run supervisor, and shutdown gracefully on interruption."""
    cfg = load_config()
    _configure_logging(cfg.settings.log_level)
    log = logging.getLogger("main")
    log.info("Configuration:\n%s", cfg)
    log.info("Starting hololens publisher session=%s", cfg.session.session_id)

    supervisor = PublisherSupervisor(cfg)
    try:
        supervisor.run()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received, stopping")
    finally:
        supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
