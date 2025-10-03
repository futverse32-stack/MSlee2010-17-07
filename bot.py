import sqlite3
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Chat
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ChatMemberHandler,
)
from config import BOT_TOKEN, OWNER_ID, DB_PATH



# Log channel/group for new users/groups
LOG_CHAT_ID = -1002962367553 # Replace with your group ID


# ---------------- Database ----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            eliminations INTEGER DEFAULT 0,
            total_score REAL DEFAULT 0,
            last_score REAL DEFAULT 0,
            penalties INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    # Groups table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            invite_link TEXT,
            added_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )

    conn.commit()
    conn.close()


def save_user(user):
    """Save user to DB, return True if new user"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user.id,))
    existing = c.fetchone()
    is_new = False
    if not existing:
        c.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
            (user.id, user.first_name, user.username),
        )
        is_new = True
    else:
        c.execute(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (user.id,)
        )
    conn.commit()
    conn.close()
    return is_new


def save_group(chat: Chat, added_by):
    """Save group info to DB"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM groups WHERE group_id = ?", (chat.id,))
    existing = c.fetchone()
    if not existing:
        invite_link = chat.invite_link if hasattr(chat, "invite_link") and chat.invite_link else "N/A"
        c.execute(
            "INSERT INTO groups (group_id, title, invite_link, added_by) VALUES (?, ?, ?, ?)",
            (chat.id, chat.title or "Private/Unknown", invite_link, added_by),
        )
    conn.commit()
    conn.close()


# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = save_user(user)

    welcome_text = """🎲 Welcome to <b>Mind Scale</b> 🎲

A stylish psychological number game where strategy meets intuition.

🔢 <b>How it works</b>
• Choose a number between 0 – 100
• Target = 80% of the group’s average
• Closest player wins the round 🏆
• Losers lose points ❌, reach −10 → eliminated ⚰️

⚡ Extra Rules unlock as players get eliminated!
Think smart. Play bold. Outsmart everyone.

👥 Play with friends in group chats.
⏱ Rounds are fast, intense, and full of surprises.
"""

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛠 Support", url="https://t.me/NexoraBots_Support"
                ),
                InlineKeyboardButton(
                    "➕ Add to Group",
                    url="https://t.me/Mindscale_GBot?startgroup=true",
                ),
            ]
        ]
    )

    # Send welcome photo with caption
    await update.message.reply_photo(
        photo="https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg",
        caption=welcome_text,
        parse_mode="HTML",
        reply_markup=buttons,
    )

    # Log new user
    if is_new:
        log_text = f"🆕 New User Joined\n" \
                   f"Name: {user.full_name}\n" \
                   f"Username: @{user.username or 'None'}\n" \
                   f"ID: {user.id}"
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=log_text)


async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when bot is added to a new group"""
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status
    old_status = update.my_chat_member.old_chat_member.status
    added_by = update.my_chat_member.from_user

    if old_status in ["kicked", "left"] and new_status in ["member", "administrator"]:
        # Send start message in the group
        welcome_text = "🎲 Hello! Mind Scale is ready to play here. Type /start to begin the fun!"
        try:
            await context.bot.send_message(chat_id=chat.id, text=welcome_text)
        except:
            pass

        # Save group to DB
        save_group(chat, f"@{added_by.username or added_by.full_name}")

        # Log new group
        group_link = chat.invite_link if hasattr(chat, "invite_link") and chat.invite_link else "N/A"
        log_text = f"🆕 New Group Added\nName: {chat.title or 'Private/Unknown'}\n" \
                   f"Link: {group_link}\nID: {chat.id}\nAdded by: @{added_by.username or added_by.full_name}"
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=log_text)
import sqlite3
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from datetime import datetime, timedelta

def stats_buttons():
    """Generate inline buttons for stats categories"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Bot Stats", callback_data="stats_bot"),
            InlineKeyboardButton("👥 User Stats", callback_data="stats_users"),
        ],
        [
            InlineKeyboardButton("🏘 Group Stats", callback_data="stats_groups"),
            InlineKeyboardButton("🌟 Top 3 Players", callback_data="stats_top_players"),
        ],
    ])

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show brief bot stats overview with buttons to view detailed categories"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Basic stats for initial message
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM groups")
    total_groups = c.fetchone()[0]

    c.execute("SELECT SUM(games_played) FROM users")
    total_games = c.fetchone()[0] or 0

    conn.close()

    overview_text = (
        f"📊 <b>Bot Statistics Overview</b> 📊\n\n"
        f"👥 <b>Total Users</b>: {total_users}\n"
        f"🏘 <b>Total Groups</b>: {total_groups}\n"
        f"🎮 <b>Total Games Played</b>: {total_games}\n\n"
        f"🔎 Select a category below for detailed stats:"
    )

    await update.message.reply_text(overview_text, parse_mode="HTML", reply_markup=stats_buttons())

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks for detailed stats"""
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Fetch all required data
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM groups")
    total_groups = c.fetchone()[0]

    c.execute("SELECT SUM(wins), SUM(losses), SUM(games_played), SUM(penalties) FROM users")
    sums = c.fetchone()
    total_wins = sums[0] or 0
    total_losses = sums[1] or 0
    total_games = sums[2] or 0
    total_penalties = sums[3] or 0

    db_size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    db_size_mb = db_size_bytes / (1024 * 1024)
    storage_percentage = (db_size_mb / 500) * 100

    seven_days_ago = datetime.datetime.now() - timedelta(days=7)
    c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE updated_at >= ?", (seven_days_ago,))
    active_users = c.fetchone()[0]

    one_day_ago = datetime.datetime.now() - timedelta(days=1)
    c.execute("SELECT COUNT(*) FROM users WHERE updated_at >= ? AND games_played > 0", (one_day_ago,))
    recent_games = c.fetchone()[0]

    avg_games_per_user = total_games / total_users if total_users > 0 else 0

    c.execute("SELECT first_name, username, wins FROM users ORDER BY wins DESC LIMIT 3")
    top_players = c.fetchall()
    top_players_info = "\n".join(
        f"{i+1}. {row[0]} (@{row[1] or 'N/A'}) - {row[2]} wins" for i, row in enumerate(top_players)
    ) if top_players else "N/A"

    c.execute("SELECT AVG(total_score) FROM users")
    avg_score = c.fetchone()[0] or 0

    c.execute("SELECT title, group_id FROM groups ORDER BY created_at DESC LIMIT 1")
    most_active_group = c.fetchone()
    most_active_group_info = f"{most_active_group[0]} (ID: {most_active_group[1]})" if most_active_group else "N/A"

    c.execute("SELECT COUNT(*) FROM users WHERE games_played = 0")
    inactive_users = c.fetchone()[0]

    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0

    c.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (seven_days_ago,))
    recent_registrations = c.fetchone()[0]

    conn.close()

    # Prepare response based on button clicked
    key = query.data.replace("stats_", "")
    if key == "bot":
        text = (
            f"📊 <b>Bot Stats</b> 📊\n\n"
            f"💾 <b>Storage Used</b>: {db_size_mb:.2f} MB / 500 MB ({storage_percentage:.2f}%)\n"
            f"🎮 <b>Total Games Played</b>: {total_games}\n"
            f"📉 <b>Win Rate</b>: {win_rate:.2f}%"
        )
    elif key == "users":
        text = (
            f"👥 <b>User Stats</b> 👥\n\n"
            f"👥 <b>Total Users</b>: {total_users}\n"
            f"🕒 <b>Active Users (last 7 days)</b>: {active_users}\n"
            f"😴 <b>Inactive Users</b>: {inactive_users}\n"
            f"🆕 <b>New Registrations (last 7 days)</b>: {recent_registrations}\n"
            f"📈 <b>Avg. Games per User</b>: {avg_games_per_user:.2f}\n"
            f"📊 <b>Average Score</b>: {avg_score:.2f}"
        )
    elif key == "groups":
        text = (
            f"🏘 <b>Group Stats</b> 🏘\n\n"
            f"🏘 <b>Total Groups</b>: {total_groups}\n"
            f"👥 <b>Most Active Group</b>: {most_active_group_info}\n"
            f"🎲 <b>Recent Games (last 24h)</b>: {recent_games}"
        )
    elif key == "top_players":
        text = (
            f"🌟 <b>Top 3 Players by Wins</b> 🌟\n\n"
            f"{top_players_info}\n\n"
            f"⚠️ <b>Total Penalties</b>: {total_penalties}\n"
            f"🏆 <b>Total Wins</b>: {total_wins}\n"
            f"❌ <b>Total Losses</b>: {total_losses}"
        )
    else:
        text = "❌ Unknown category"

    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=stats_buttons())


import game
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

# ---------------- /getid COMMAND ----------------
async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    DM command: reply to a video and send its file_id
    """
    if update.effective_chat.type != "private":
        await update.message.reply_text("This command only works in DMs with the bot.")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.video:
        await update.message.reply_text("❌ Reply to a video message to get its file_id.")
        return

    file_id = reply.video.file_id
    await update.message.reply_text(f"✅ Video file_id:\n<code>{file_id}</code>", parse_mode="HTML")

import game
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

# ---------------- /getid COMMAND ----------------
async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    DM command: reply to a video and send its file_id
    """
    if update.effective_chat.type != "private":
        await update.message.reply_text("This command only works in DMs with the bot.")
        return

    reply = update.message.reply_to_message
    if not reply or not reply.video:
        await update.message.reply_text("❌ Reply to a video message to get its file_id.")
        return

    file_id = reply.video.file_id
    await update.message.reply_text(f"✅ Video file_id:\n<code>{file_id}</code>", parse_mode="HTML")
from telegram import Message, Update
from telegram.ext import ContextTypes
import sqlite3
import asyncio
from functools import partial
import logging

# Set up logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_ids():
    """Fetch group and user IDs in a separate thread."""
    loop = asyncio.get_event_loop()
    def get_ids():
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT group_id FROM groups")
            groups = [row[0] for row in c.fetchall()]
            c.execute("SELECT user_id FROM users")
            users = [row[0] for row in c.fetchall()]
            conn.close()
            return groups, users
        except Exception as e:
            logger.error(f"Error fetching IDs: {e}")
            return [], []
    return await loop.run_in_executor(None, get_ids)

async def broadcast_task(bot, reply: Message, groups: list, users: list):
    """Background broadcast fully detached from update"""
    success_groups = 0
    success_users = 0

    # Broadcast to groups
    for gid in groups:
        try:
            await reply.forward(chat_id=gid)
            success_groups += 1
            await asyncio.sleep(0)  # yield control
        except Exception:
            continue

    # Broadcast to users
    for uid in users:
        try:
            await reply.forward(chat_id=uid)
            success_users += 1
            await asyncio.sleep(0)  # yield control
        except Exception:
            continue

    # Log result to owner
    try:
        await bot.send_message(
            chat_id=OWNER_ID,
            text=f"✅ Broadcast done!\nGroups: {success_groups}/{len(groups)}\nUsers: {success_users}/{len(users)}"
        )
    except Exception:
        pass



async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a replied message to all users and groups (OWNER ONLY)"""
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    reply: Message = update.message.reply_to_message
    if not reply:
        await update.message.reply_text("❌ Reply to a message to broadcast it.")
        return

    # Confirm broadcast start
    try:
        await update.message.reply_text("🚀 Broadcasting message to all users and groups...")
    except Exception as e:
        logger.error(f"Failed to send broadcast start message: {e}")
        return

    # Fetch IDs in a separate thread
    try:
        groups, users = await fetch_ids()
    except Exception as e:
        logger.error(f"Failed to fetch IDs: {e}")
        await update.message.reply_text("❌ Failed to fetch recipients. Try again later.")
        return

    # Run broadcast in background
    asyncio.create_task(broadcast_task(reply, groups, users, update, context))
import os
import shutil
import datetime
import asyncio
from telegram import Update, InputFile
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

BACKUP_FOLDER = "backups"  # folder to store auto backups
os.makedirs(BACKUP_FOLDER, exist_ok=True)

# ---------------- /backup COMMAND ----------------
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
        await update.message.reply_text(f"❌ Failed to create/send backup: {e}")

# ---------------- Auto backup every 12 hours ----------------
async def auto_backup(app):
    while True:
        try:
            backup_path = os.path.join(BACKUP_FOLDER, f"auto_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
            shutil.copyfile(DB_PATH, backup_path)
            with open(backup_path, "rb") as f:
                await app.bot.send_document(chat_id=OWNER_ID, document=InputFile(f, filename=os.path.basename(backup_path)),
                                            caption="💾 Auto backup (every 12 hours)")
        except Exception as e:
            print(f"Auto backup failed: {e}")
        await asyncio.sleep(12 * 3600)  # 12 hours

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
        file_obj = await file.get_file()  # await the coroutine
        file_path = os.path.join(BACKUP_FOLDER, f"restore_{file.file_name}")
        await file_obj.download_to_drive(file_path)  # await the download

        # Overwrite current database
        shutil.copyfile(file_path, DB_PATH)
        await update.message.reply_text("✅ Database restored successfully!")
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to restore database: {e}")
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ContextTypes

GUIDE_TEXTS = {
    "commands": (
        "📜 <b>Commands:</b>\n"
        "/start - Start the bot\n"
        "/stats - Show bot stats\n"
        "/getid - Get file_id of media\n"
        "/bcast - Broadcast text (owner only)\n"
        "/fcast - Forward broadcast (owner only)\n"
        "/backup - Backup DB (owner only)\n"
        "/restore - Restore DB (owner only)\n"
        "/startgame - Start a new game\n"
        "/join - Join the current game\n"
        "/leave - Leave the current game\n"
        "/players - Show joined players\n"
        "/endgame - End the ongoing match\n"
        "/guide - Show guide\n"
        "/userinfo - Show your stats"
    ),
    "howtoplay": (
        "🎲 <b>How to Play:</b>\n"
        "1. Join a game using /join when a game is active.\n"
        "2. The game master (bot) will start the round using /startgame.\n"
        "3. Each round, choose a number between 0-100.\n"
        "4. Send your number <b>in a private message to the bot</b>.\n"
        "5. The target number for the round is 80% of the group's average.\n"
        "6. The player closest to the target wins the round 🏆.\n"
        "7. Duplicate numbers or invalid input may incur penalty points.\n"
        "8. If your score reaches −10, you are eliminated ⚰️.\n"
        "9. The last player standing wins the game!\n\n"
        "💡 <i>Tip:</i> Always send your number privately to the bot to avoid giving hints to other players."
    ),
    "rules": (
        "⚖️ <b>Game Rules:</b>\n"
        "1. Only numbers between 0-100 are accepted.\n"
        "2. Each round, all players must send their number <b>privately to the bot</b>.\n"
        "3. Round losers get -1 point as penalty.\n"
        "4. Round winners are safe and do not lose points.\n"
        "5. If your score reaches −10 points, you are eliminated from the game ⚰️.\n"
        "6. Duplicate numbers or invalid inputs may incur additional penalties.\n"
        "7. The last player standing wins the game 🏆."
    ),
    "elimination": (
        "☠️ <b>Elimination Rules:</b>\n"
        "1️⃣ <b>Duplicate Penalty Rule (activates after 4+ players pick the same number or first elimination):</b>\n"
        "   • When active, if 4 or more players pick the same number, each gets −1 point.\n"
        "   • Players with unique numbers or numbers picked by fewer than 4 players are safe.\n\n"
        "2️⃣ <b>After 2 players are out:</b>\n"
        "   • If a player picks the <b>exact target number</b>, all other players lose −2 points.\n\n"
        "3️⃣ <b>After 3 players are out:</b>\n"
        "   • If one player picks 0 and another picks 100 in the same round, the player who picked 100 wins automatically.\n\n"
        "💡 <i>Tip:</i> Watch for duplicate numbers after the rule activates, and avoid extreme numbers in late rounds to stay safe!"
    ),
    "advice": (
        "💡 <b>General Advice:</b>\n\n"
        "• <b>Early rounds:</b> Play safe (stay around 20–40).\n"
        "• <b>Middle rounds:</b> Start reading patterns (who is playing greedy, who plays safe).\n"
        "• <b>Late rounds:</b> Bluff, bait, and play unpredictably."
    )
}
def guide_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Commands", callback_data="guide_commands"),
            InlineKeyboardButton("How to Play", callback_data="guide_howtoplay")
        ],
        [
            InlineKeyboardButton("Game Rules", callback_data="guide_rules"),
            InlineKeyboardButton("Elimination Rules", callback_data="guide_elimination")
        ],
        [
            InlineKeyboardButton("General Advice", callback_data="guide_advice")
        ]
    ])

# ---------------- /guide COMMAND ----------------
async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send guide video with buttons."""
    caption = "🎲 <b>Welcome to Mind Scale Guide!</b>\nChoose a topic from below:"
    video_url = "BAACAgUAAyEFAAS3OY5mAAIRDmjcsfFxkL5irxrkFdWXeMfCX3fmAAIDHQAC00rpVil8MdHStP21NgQ"  # Replace with your guide video

    await update.message.reply_video(
        video=video_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=guide_buttons()
    )
async def guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Always acknowledge

    key = query.data.replace("guide_", "")  # Remove prefix
    text = GUIDE_TEXTS.get(key, "❌ Unknown section")

    await query.edit_message_caption(
        caption=text,
        parse_mode="HTML",
        reply_markup=guide_buttons()
    )

# -------------------- BUG REPORT COMMAND --------------------
  # replace with your log group id

async def bugs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat

    # Get bug text after command
    if not context.args:
        await update.message.reply_text(
            "⚠️ Please provide a bug description.\n\nExample:\n`/bugs Scoring not working properly`",
            parse_mode="Markdown"
        )
        return

    bug_text = " ".join(context.args)

    # Acknowledge user
    await update.message.reply_text("✅ Thanks! Your bug has been reported to the developers.")

    # Forward / send to log group
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
from telegram.ext import ApplicationBuilder



#
if __name__ == "__main__":
    # Init database
    init_db()

    # Build app
    app = ApplicationBuilder().token(BOT_TOKEN).build()

  # Add owner handlers in group 0 (default)

    # ---------------- Group 1: Game Handlers ----------------
    import game
    game.register_handlers  # Add game handlers in group 1

    # ---------------- Other Command Handlers (Group 0) ----------------
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats_"))

    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("cast", broadcast_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("restore", restore_command))

    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CallbackQueryHandler(guide_callback, pattern="^guide_"))


    app.add_handler(CommandHandler("reset", reset))
    # ---------------- ChatMember Handler (bot added to group) ----------------
    app.add_handler(ChatMemberHandler(bot_added, ChatMemberHandler.MY_CHAT_MEMBER))

    # ---------------- Background Tasks ----------------
    # Start auto backup loop
    app.job_queue.run_repeating(lambda ctx: asyncio.create_task(auto_backup(app)), interval=12*3600, first=10)

    import owner
    owner.register_owner_handlers

    # ---------------- Run ----------------
    print("✅ Bot is running...")
    app.run_polling()
