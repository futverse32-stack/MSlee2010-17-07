from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from plugins.connections.logger import setup_logger
from plugins.connections.db import init_db
from plugins.utils.cleanup import clean_temp_job
from datetime import timedelta


logger = setup_logger("mind-scale-bot")

if __name__ == "__main__":
    # Init DB
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    try:
        from plugins.game import game_handlers
        game_handlers(app)
    except Exception:
        logger.exception("Failed to load Game module")

    try:
        from plugins.helpers import helpers_handlers
        helpers_handlers(app)
    except Exception:
        logger.exception("Failed to load Helpers module")
    
    app.job_queue.run_repeating(
        clean_temp_job,
        interval=timedelta(hours=12),
        first=300           
    )

    print("✅ Bot is running...")
    app.run_polling()
