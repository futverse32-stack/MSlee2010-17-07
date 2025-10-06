from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, filters
from plugins.game.db import init_user_table, init_group_table, ensure_gstats_tables, ensure_games_table
from plugins.game.lobby import startgame, join, leave, players, endmatch, forcestart, mode_selection, confirm_endmatch, extend
from plugins.game.core import dm_pick_handler
import logging

logger = logging.getLogger(__name__)

def game_handlers(app):
    init_user_table()
    init_group_table()
    ensure_games_table()
    ensure_gstats_tables()


    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("extend", extend))
    app.add_handler(CommandHandler("players", players))
    app.add_handler(CommandHandler("endgame", endmatch))
    app.add_handler(CommandHandler("forcestart", forcestart))

    app.add_handler(CallbackQueryHandler(confirm_endmatch, pattern=r"^confirm_endmatch:-?\d+$"))
    app.add_handler(CallbackQueryHandler(mode_selection, pattern=r"^(start_solo|start_team):-?\d+$"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, dm_pick_handler))
    logger.info("Game handlers loaded successfully")

__all__ = ["game_handlers"]
