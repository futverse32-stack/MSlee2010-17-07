import os
import shutil
import logging
import glob, re
from datetime import datetime, timedelta
from telegram import Update, InputFile
from telegram.ext import ContextTypes, CommandHandler
from plugins.utils.decorators import owner_only, mod_or_owner

from config import DB_PATH, OWNER_ID, BACKUP_FOLDER, LOG_CHAT_ID

logger = logging.getLogger(__name__)

os.makedirs(BACKUP_FOLDER, exist_ok=True)


# ---------- Helpers ----------
def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _backup_path(prefix: str) -> str:
    return os.path.join(BACKUP_FOLDER, f"{prefix}_{_timestamp()}.db")


def _ensure_backups_dir():
    try:
        os.makedirs(BACKUP_FOLDER, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to ensure backups dir: {e}")


async def _create_backup_file(prefix: str) -> str:
    """
    Create a copy of DB_PATH into backups/ and return the file path.
    """
    _ensure_backups_dir()
    dst = _backup_path(prefix)
    shutil.copyfile(DB_PATH, dst)
    return dst


async def _send_backup_to_owner(context: ContextTypes.DEFAULT_TYPE, file_path: str, caption: str | None = None):
    with open(file_path, "rb") as f:
        m = await context.bot.send_document(
            chat_id=OWNER_ID,
            document=InputFile(f, filename=os.path.basename(file_path)),
            caption=caption or ""
        )
        await m.forward(LOG_CHAT_ID)

def prune_auto_backups(keep: int = 1):
    pattern = os.path.join(BACKUP_FOLDER, "auto_backup_*.db")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    to_delete = files[keep:]
    for path in to_delete:
        try:
            if re.search(r"auto_backup_\d{8}_\d{6}\.db$", os.path.basename(path)):
                os.remove(path)
        except Exception as e:
            logger.warning(f"Failed to delete old auto backup {path}: {e}")

# ---------- Commands ----------
@mod_or_owner
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:
        await update.message.reply_text("💾 Preparing database backup...")
        path = await _create_backup_file("manual_backup")
        await _send_backup_to_owner(context, path, caption="💾 Manual backup")
        await update.message.reply_text("✅ Backup sent to your DM!")
    except Exception as e:
        logger.exception("Backup failed")
        await update.message.reply_text(f"❌ Failed to create/send backup: {e}")

@mod_or_owner
async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    reply = update.message.reply_to_message
    if not reply or not reply.document:
        await update.message.reply_text("❌ Reply to a backup `.db` file to restore.")
        return

    file = reply.document
    if not file.file_name.endswith(".db"):
        await update.message.reply_text("❌ This is not a valid database file.")
        return

    try:
        await update.message.reply_text("💾 Downloading backup file...")
        tg_file = await file.get_file()
        _ensure_backups_dir()
        temp_restore_path = os.path.join(BACKUP_FOLDER, f"restore_{file.file_name}")
        await tg_file.download_to_drive(temp_restore_path)

        try:
            safety_path = await _create_backup_file("pre_restore_backup")
            logger.info(f"Pre-restore safety backup: {safety_path}")
        except Exception as e:
            logger.warning(f"Could not create pre-restore backup: {e}")

        shutil.copyfile(temp_restore_path, DB_PATH)

        await update.message.reply_text("✅ Database restored successfully!")
    except Exception as e:
        logger.exception("Restore failed")
        await update.message.reply_text(f"❌ Failed to restore database: {e}")


# ---------- Jobs ----------
async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs via JobQueue every 12 hours. Creates a backup and sends to OWNER_ID.
    """
    try:
        path = await _create_backup_file("auto_backup")
        await _send_backup_to_owner(context, path, caption="💾 Auto backup (every 12 hours)")
    except Exception as e:
        logger.exception("Auto backup failed")
        try:
            await context.bot.send_message(chat_id=LOG_CHAT_ID, text=f"❌ Auto backup failed: {e}")
        except Exception:
            pass
    prune_auto_backups(keep=1)

# -------------------- BUG REPORT COMMAND --------------------

async def bugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide a bug description.\n\nExample:\n`/bugs Scoring not working properly`",
            parse_mode="Markdown"
        )
        return

    bug_text = " ".join(context.args)

    await update.message.reply_text("✅ Thanks! Your bug has been reported to the developers.")

    report_msg = (
        f"🐞 <b>Bug Report</b>\n\n"
        f"<b>Bug:</b> {bug_text}\n"
        f"<b>Found by:</b> {user.mention_html()}\n"
        f"<b>User ID:</b> <code>{user.id}</code>\n"
        f"<b>From Chat:</b> {chat.title if chat.type != 'private' else 'Private Chat'}"
    )

    await context.bot.send_message(
        chat_id=LOG_CHAT_ID,
        text=report_msg,
        parse_mode="HTML"
    )