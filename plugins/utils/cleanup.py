import shutil
from pathlib import Path
import logging
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

TEMP_DIR = Path("temp")

async def clean_temp_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Deletes the entire temp folder and recreates it.
    """
    try:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
            logger.info("Temp folder removed.")
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("Temp folder recreated.")
    except Exception:
        logger.exception("Failed to clean temp folder")
