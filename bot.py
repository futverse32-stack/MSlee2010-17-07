import asyncio
from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from plugins.connections.logger import setup_logger
from plugins.connections.db import init_db


logger = setup_logger("mindful-muse-bot")

if __name__ == "__main__":
    # Init DB
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    try:
        from plugins.game import register_handlers as register_game_handlers
        register_game_handlers(app)
    except Exception:
        logger.exception("Failed to load Game module")

    try:
        from plugins.helpers import helpers_handlers as register_helpers_handlers
        register_helpers_handlers(app)
    except Exception:
        logger.exception("Failed to load Helpers module")

    print("✅ Bot is running...")
    app.run_polling()
