import sqlite3
import asyncio
import os
import shutil
import datetime
from telegram import Message, Update, InputFile
from telegram.ext import ContextTypes
from config import DB_PATH, OWNER_ID, BACKUP_FOLDER
from plugins.connections.logger import setup_logger

logger = setup_logger(__name__)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

async def fetch_ids(db_path):
    """Fetch group and user IDs in a separate thread."""
    loop = asyncio.get_event_loop()
    def get_ids():
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT group_id FROM groups")
            groups = [row[0] for row in c.fetchall()]
            c.execute("SELECT user_id FROM users")
            users = [row[0] for row in c.fetchall()]
            conn.close()
            return groups, users
        except Exception as e:
            logger.error("Error fetching IDs: %s", e)
            return [], []
    return await loop.run_in_executor(None, get_ids)

async def broadcast_task(bot, reply: Message, groups: list, users: list, owner_id: int):
    """Background broadcast fully detached from update."""
    success_groups = 0
    success_users = 0

    # Broadcast to groups
    for gid in groups:
        try:
            await reply.forward(chat_id=gid)
            success_groups += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.debug("Failed to forward to group %s: %s", gid, e)
            continue

    # Broadcast to users
    for uid in users:
        try:
            await reply.forward(chat_id=uid)
            success_users += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.debug("Failed to forward to user %s: %s", uid, e)
            continue

    # Log result to owner
    try:
        await bot.send_message(
            chat_id=owner_id,
            text=f"✅ Broadcast done!\nGroups: {success_groups}/{len(groups)}\nUsers: {success_users}/{len(users)}"
        )
    except Exception as e:
        logger.error("Failed to send broadcast completion message to owner: %s", e)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a replied message to all users and groups (OWNER ONLY)."""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply: Message = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Reply to a message to broadcast it.")
        return

    try:
        await update.message.reply_text("🚀 Broadcasting message to all users and groups...")
    except Exception:
        logger.debug("Failed to send broadcast start message")

    try:
        groups, users = await fetch_ids(DB_PATH)
    except Exception as e:
        logger.exception("Failed to fetch IDs: %s", e)
        await update.message.reply_text("❌ Failed to fetch recipients. Try again later.")
        return

    try:
        asyncio.create_task(broadcast_task(context.bot, reply, groups, users, OWNER_ID))
        logger.info("Broadcast task started in background")
    except Exception as e:
        logger.exception("Failed to start broadcast task: %s", e)
        await update.message.reply_text("❌ Failed to start broadcast. Try again later.")


# ---------------- Backup & Restore ----------------
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    try:
        await update.message.reply_text("💾 Preparing database backup...")
        backup_path = os.path.join(BACKUP_FOLDER, f"db_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
        shutil.copyfile(DB_PATH, backup_path)

        with open(backup_path, "rb") as f:
            await context.bot.send_document(chat_id=OWNER_ID, document=InputFile(f, filename=os.path.basename(backup_path)))

        await update.message.reply_text("✅ Backup sent to your DM!")
    except Exception as e:
        logger.exception("Failed to create/send backup: %s", e)
        await update.message.reply_text(f"❌ Failed to create/send backup: {e}")


async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

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
        file_obj = await file.get_file()
        file_path = os.path.join(BACKUP_FOLDER, f"restore_{file.file_name}")
        await file_obj.download_to_drive(file_path)

        # Overwrite current database
        shutil.copyfile(file_path, DB_PATH)
        await update.message.reply_text("✅ Database restored successfully!")
    except Exception as e:
        logger.exception("Failed to restore DB: %s", e)
        await update.message.reply_text(f"❌ Failed to restore database: {e}")
