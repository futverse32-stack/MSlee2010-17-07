# plugins/helpers/mods.py
import sqlite3
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from config import DB_PATH, OWNER_ID, LOG_CHAT_ID
import logging

logger = logging.getLogger(__name__)

# ---------------- Database Initialization for Mods ----------------
def init_mods_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS mods (
            mod_id INTEGER PRIMARY KEY,
            username TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

# ---------------- Helper Functions ----------------
def is_owner(user_id: int) -> bool:
    """Check if the user is the owner."""
    return user_id == OWNER_ID

def is_mod(user_id: int) -> bool:
    """Check if the user is a mod."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (user_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def add_mod(mod_id: int, username: str) -> bool:
    """Add a mod to the DB if not exists. Returns True if added."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (mod_id,))
    if c.fetchone():
        conn.close()
        return False  # Already exists
    c.execute("INSERT INTO mods (mod_id, username) VALUES (?, ?)", (mod_id, username))
    conn.commit()
    conn.close()
    return True

def remove_mod(mod_id: int) -> bool:
    """Remove a mod from the DB. Returns True if removed."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id FROM mods WHERE mod_id = ?", (mod_id,))
    if not c.fetchone():
        conn.close()
        return False  # Not exists
    c.execute("DELETE FROM mods WHERE mod_id = ?", (mod_id,))
    conn.commit()
    conn.close()
    return True

def get_all_mods() -> list:
    """Get list of all mods as (mod_id, username)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT mod_id, username FROM mods")
    mods = c.fetchall()
    conn.close()
    return mods

def reset_user_stats(user_id: int) -> bool:
    """Reset a user's stats in the users table. Returns True if user exists and reset."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        conn.close()
        return False
    c.execute(
        """
        UPDATE users
        SET games_played = 0,
            wins = 0,
            losses = 0,
            rounds_played = 0,
            eliminations = 0,
            total_score = 0,
            last_score = 0,
            penalties = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (user_id,)
    )
    conn.commit()
    conn.close()
    return True

# ---------------- Command Handlers ----------------
async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Add a mod by replying to a user."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.from_user:
        await update.message.reply_text("❌ Reply to a user's message to add them as mod.")
        return

    mod_user = reply.from_user
    if add_mod(mod_user.id, mod_user.username or mod_user.full_name):
        await update.message.reply_text(f"✅ Added @{mod_user.username or mod_user.full_name} as mod.")
        # Log to LOG_CHAT_ID if exists
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, f"🆕 New Mod Added: @{mod_user.username or mod_user.full_name} (ID: {mod_user.id}) by Owner.")
            except Exception:
                logger.exception("Failed to log new mod to LOG_CHAT_ID")
    else:
        await update.message.reply_text("⚠️ This user is already a mod.")

async def rmmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: Remove a mod by replying or providing userid."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    mod_id = None
    if context.args:
        try:
            mod_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Provide a number or reply to a user.")
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        mod_id = update.message.reply_to_message.from_user.id

    if not mod_id:
        await update.message.reply_text("❌ Provide a user ID or reply to a user's message to remove mod.")
        return

    if remove_mod(mod_id):
        await update.message.reply_text(f"✅ Removed mod with ID {mod_id}.")
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, f"❌ Mod Removed: ID {mod_id} by Owner.")
            except Exception:
                logger.exception("Failed to log mod removal to LOG_CHAT_ID")
    else:
        await update.message.reply_text("⚠️ No such mod found.")

async def mods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: List all mods."""
    user = update.effective_user
    if not is_owner(user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    mod_list = get_all_mods()
    if not mod_list:
        await update.message.reply_text("❌ No mods added yet.")
        return

    text = "📋 List of Mods:\n\n"
    for i, (mod_id, username) in enumerate(mod_list, 1):
        text += f"{i}. @{username or 'N/A'} (ID: {mod_id})\n"

    await update.message.reply_text(text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mod/Owner-only: Reset user stats by userid or reply."""
    user = update.effective_user
    if not (is_owner(user.id) or is_mod(user.id)):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    target_id = None
    if context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Provide a number or reply to a user.")
            return
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id

    if not target_id:
        await update.message.reply_text("❌ Provide a user ID or reply to a user's message to reset stats.")
        return

    if reset_user_stats(target_id):
        await update.message.reply_text(f"✅ Reset stats for user ID {target_id}.")
        if LOG_CHAT_ID:
            try:
                await context.bot.send_message(LOG_CHAT_ID, f"🔄 User Stats Reset: ID {target_id} by @{user.username or user.full_name} (ID: {user.id}).")
            except Exception:
                logger.exception("Failed to log user reset to LOG_CHAT_ID")
    else:
        await update.message.reply_text("⚠️ No such user found in the database.")

# ---------------- Register Handlers ----------------
def register_mods_handlers(app):
    init_mods_db() 
    app.add_handler(CommandHandler("addmod", addmod))
    app.add_handler(CommandHandler("rmmod", rmmod))
    app.add_handler(CommandHandler("mods", mods))
    app.add_handler(CommandHandler("reset", reset))
