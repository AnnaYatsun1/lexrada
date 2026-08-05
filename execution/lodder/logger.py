import logging
import logging.config

from execution.lodder.logging_config import LOGGING_CONFIG


def setup_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)


def get_logger(name: str = "contract_analyzer") -> logging.Logger:
    return logging.getLogger(name)