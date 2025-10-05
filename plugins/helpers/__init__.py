from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, filters, ChatMemberHandler
from plugins.helpers.start import start, bot_added
from plugins.helpers.gstats import gstats, gstats_callback
from plugins.helpers.stats import stats, stats_callback
from plugins.helpers.guide import guide_command, guide_callback
from plugins.helpers.broadcast import broadcast_command, backup_command, restore_command
from plugins.helpers.leaderboard import leaderboard_command, leaderboard_callback, users_rank as users_rank_command
from plugins.helpers.moderators import register_mods_handlers

import logging

logger = logging.getLogger(__name__)

def helpers_handlers(app):
    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("gstats", gstats))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats_"))
    app.add_handler(CallbackQueryHandler(gstats_callback, pattern="^gstats_"))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CallbackQueryHandler(guide_callback, pattern="^guide_"))

    # Leaderboard under helpers
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard_"))
    app.add_handler(CommandHandler("users_rank", users_rank_command))

    #Mods Commands
    register_mods_handlers(app)
    
    # Owner / admin commands
    app.add_handler(CommandHandler("cast", broadcast_command))    # forward broadcast
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("restore", restore_command))

    # ChatMember (bot added to group)
    app.add_handler(ChatMemberHandler(bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    logger.info("Helpers handlers registered")

__all__ = ["helpers_handlers"]
