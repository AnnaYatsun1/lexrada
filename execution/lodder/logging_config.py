from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "default": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        }
    },

    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 5_000_000,
            "backupCount": 5,
            "formatter": "default",
            "encoding": "utf-8"
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default"
        }
    },

    "loggers": {
        "contract_analyzer": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False
        }
    }
}