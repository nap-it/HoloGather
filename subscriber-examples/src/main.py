"""Subscriber Hub Application entrypoint.

`main.py` acts as the composition root: it loads centralized configuration,
configures logging, instantiates the process supervisor, and runs until stop.
"""

from __future__ import annotations

import logging
import sys

from src.utils.config import build_argparser, from_everywhere, AppConfig
from src.runtime.supervisor import SubscriberSupervisor


def _configure_logging(level: str) -> None:
    """Configure global logging once from config center log level."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def main() -> int:
    """Load config, run supervisor, and shutdown gracefully on interruption."""
    parser = build_argparser()
    args = parser.parse_args()
    cfg: AppConfig = from_everywhere(args)
    
    _configure_logging(cfg.log_level)
    log = logging.getLogger("main")
    log.info("Configuration:\n%s", cfg)
    log.info("Starting hololens subscriber for user_id=%s", cfg.hololens_user_id)

    supervisor = SubscriberSupervisor(cfg)
    try:
        supervisor.run()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt received, stopping")
    finally:
        supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
