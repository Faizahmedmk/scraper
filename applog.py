"""File logging. Writes to logs/app.log (override with LOG_FILE); rotates at 1 MB, keeps 5 files."""
import logging
import os
from logging.handlers import RotatingFileHandler

_here = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.environ.get("LOG_FILE") or os.path.join(_here, "logs", "app.log")
_ready = False


def setup(level=logging.INFO):
    """Attach the file handler to the root logger once. Never raises."""
    global _ready
    root = logging.getLogger()
    if _ready:
        return root
    _ready = True
    root.setLevel(level)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        h = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
    except OSError:
        logging.basicConfig(level=level)   # falls back to stderr (Passenger's log)
    return root
