"""Entry point for cPanel 'Setup Python App' (Phusion Passenger)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import applog  # noqa: E402

applog.setup()

try:
    from app import app as application  # noqa: E402
except Exception:
    import logging
    logging.getLogger("startup").exception("App failed to start")   # traceback lands in logs/app.log
    raise
