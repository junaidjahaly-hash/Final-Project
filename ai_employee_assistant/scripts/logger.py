from loguru import logger
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
log_dir = BASE_DIR / "logs"
log_dir.mkdir(exist_ok=True)

logger.remove()  # Remove default handler
logger.add(
    log_dir / "app.log",
    rotation="00:00",  # daily rotation
    retention="10 days",
    level="INFO",
    backtrace=True,
    diagnose=True,
)
logger.add(sys.stderr, level="DEBUG")

__all__ = ["logger"]
