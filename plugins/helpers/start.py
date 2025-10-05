# helpers/start.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from plugins.connections.db import save_user, save_group
from config import LOG_CHAT_ID
from plugins.connections.logger import setup_logger

logger = setup_logger(__name__)

WELCOME_IMAGE = "https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg"

WELCOME_TEXT = """🎲 Welcome to <b>Mind Scale</b> 🎲

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

def start_buttons():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛠 Support", url="https://t.me/NexoraBots_Support"),
                InlineKeyboardButton("➕ Add to Group", url="https://t.me/Mindscale_GBot?startgroup=true"),
            ]
        ]
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = False
    try:
        is_new = save_user(user)
    except Exception as e:
        logger.exception("Failed to save user: %s", e)

    # Reply with welcome image + caption
    try:
        await update.message.reply_photo(
            photo=WELCOME_IMAGE,
            caption=WELCOME_TEXT,
            parse_mode="HTML",
            reply_markup=start_buttons()
        )
    except Exception as e:
        logger.exception("Failed to send welcome message: %s", e)

    # Log new user to log channel
    if is_new:
        try:
            log_text = (
                f"🆕 New User Joined\n"
                f"Name: {user.full_name}\n"
                f"Username: @{user.username or 'None'}\n"
                f"ID: {user.id}"
            )
            await context.bot.send_message(chat_id=LOG_CHAT_ID, text=log_text)
        except Exception:
            logger.exception("Failed to log new user to LOG_CHAT_ID")


async def bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called on ChatMember update when the bot is added to a group
    """
    try:
        chat = update.my_chat_member.chat
        new_status = update.my_chat_member.new_chat_member.status
        old_status = update.my_chat_member.old_chat_member.status
        added_by = update.my_chat_member.from_user

        if old_status in ["kicked", "left"] and new_status in ["member", "administrator"]:
            # Send a small welcome in group (best-effort)
            welcome_text = "🎲 Hello! Mind Scale is ready to play here. Type /start to begin the fun!"
            try:
                await context.bot.send_message(chat_id=chat.id, text=welcome_text)
            except Exception:
                logger.debug("Could not send message to new group (bot may lack permission)")

            # Save group to DB
            try:
                save_group(chat, f"@{added_by.username or added_by.full_name}")
            except Exception:
                logger.exception("Failed to save new group to DB.")

            # Log group to log channel
            try:
                group_link = chat.invite_link if hasattr(chat, "invite_link") and chat.invite_link else "N/A"
                log_text = (
                    f"🆕 New Group Added\nName: {chat.title or 'Private/Unknown'}\n"
                    f"Link: {group_link}\nID: {chat.id}\nAdded by: @{added_by.username or added_by.full_name}"
                )
                await context.bot.send_message(chat_id=LOG_CHAT_ID, text=log_text)
            except Exception:
                logger.exception("Failed to log new group to LOG_CHAT_ID")
    except Exception as e:
        logger.exception("Error in bot_added handler: %s", e)
