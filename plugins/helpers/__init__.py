from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, filters, ChatMemberHandler
from plugins.helpers.start import start, bot_added
from plugins.helpers.gstats import gstats, gstats_callback
from plugins.helpers.stats import stats, stats_callback, getid_command
from plugins.helpers.guide import guide_command, guide_callback
from plugins.helpers.broadcast import broadcast_command
from plugins.helpers.leaderboard import leaderboard_command, leaderboard_callback, users_rank as users_rank_command, userinfo
from plugins.helpers.moderators import register_mods_handlers
from plugins.helpers.backup import auto_backup_job, restore_command, backup_command, bugs
from plugins.helpers.notify import notify_handlers
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def helpers_handlers(app):
    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("bugs", bugs))
    app.add_handler(CommandHandler("gstats", gstats))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats_"))
    app.add_handler(CallbackQueryHandler(gstats_callback, pattern="^gstats_"))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CallbackQueryHandler(guide_callback, pattern="^guide_"))

    # Leaderboard
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard_"))
    app.add_handler(CommandHandler("users_rank", users_rank_command))
    app.add_handler(CommandHandler("userinfo", userinfo))

    #Mods Commands
    register_mods_handlers(app)

    #notification
    notify_handlers(app)
    
    # Owner / admin commands
    app.add_handler(CommandHandler("cast", broadcast_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("restore", restore_command))

    # Schedule auto backup: every 12 hours
    app.job_queue.run_repeating(
        auto_backup_job,
        interval=timedelta(hours=12),
        first=timedelta(seconds=10),
        name="auto_backup_job",
    )

    app.add_handler(ChatMemberHandler(bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    logger.info("Helpers handlers loaded successfully")

__all__ = ["helpers_handlers"]
