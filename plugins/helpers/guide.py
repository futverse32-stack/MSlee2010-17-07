# helpers/guide.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from plugins.connections.logger import setup_logger

logger = setup_logger(__name__)

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

VIDEO_ID = "BAACAgUAAyEFAAS3OY5mAAIRDmjcsfFxkL5irxrkFdWXeMfCX3fmAAIDHQAC00rpVil8MdHStP21NgQ"

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = "🎲 <b>Welcome to Mind Scale Guide!</b>\nChoose a topic from below:"
    try:
        await update.message.reply_video(
            video=VIDEO_ID,
            caption=caption,
            parse_mode="HTML",
            reply_markup=guide_buttons()
        )
    except Exception:
        logger.exception("Failed to send guide video")


async def guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    key = query.data.replace("guide_", "")
    text = GUIDE_TEXTS.get(key, "❌ Unknown section")

    try:
        await query.edit_message_caption(
            caption=text,
            parse_mode="HTML",
            reply_markup=guide_buttons()
        )
    except Exception:
        logger.exception("Failed to update guide caption")
