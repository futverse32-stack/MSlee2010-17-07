import sqlite3
from typing import List, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

from config import DB_PATH

# ---------------- DB ----------------
def _conn():
    return sqlite3.connect(DB_PATH)

def init_notify_db():
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_optins (
                group_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                first_name TEXT,
                PRIMARY KEY (group_id, user_id)
            )
            """
        )
        conn.commit()

def add_optin(group_id: int, user_id: int, first_name: str):
    with _conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO notify_optins (group_id, user_id, first_name) VALUES (?, ?, ?)",
            (group_id, user_id, first_name or "")
        )
        conn.commit()

def remove_optin(group_id: int, user_id: int):
    with _conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM notify_optins WHERE group_id = ? AND user_id = ?", (group_id, user_id))
        conn.commit()

def get_optins(group_id: int) -> List[Tuple[int, str]]:
    with _conn() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, COALESCE(first_name,'') FROM notify_optins WHERE group_id = ?", (group_id,))
        return [(row[0], row[1]) for row in c.fetchall()]

# ---------------- Utils ----------------
def mention_html(uid: int, name: str) -> str:
    safe = (name or "player").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={uid}">{safe}</a>'

async def _reply(update: Update, text: str):
    try:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except:
        pass

def _usage_text(chat_title: str | None = None) -> str:
    return (
        "❓ <b>How to use</b>\n"
        "• <code>/notify on</code> — subscribe to new-game alerts in this group\n"
        "• <code>/notify off</code> — unsubscribe\n\n"
    )

# ---------------- Single /notify handler ----------------
async def notify_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    args = context.args if context.args is not None else []

    # Require group/supergroup
    if not chat or chat.type not in ("group", "supergroup"):
        await _reply(update, "Use <code>/notify on</code> or <code>/notify off</code> in the game group so I know where to tag you.\n\n" + _usage_text(None))
        return

    # Validate args: exactly one token: "on" or "off"
    if len(args) != 1 or args[0].lower() not in ("on", "off"):
        await _reply(update, "⚠️ Invalid format.\n\n" + _usage_text(chat.title))
        return

    mode = args[0].lower()

    if mode == "on":
        add_optin(chat.id, user.id, user.first_name or "")
        await _reply(
            update,
            "✅ You’ll be notified when a new game starts here.\n🌿 Use <code>/notify off</code> to pause."
        )
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"🔔 You subscribed to new game alerts in <code>{chat.title}</code>.",
                parse_mode=ParseMode.HTML,
            )
        except:
            pass

    else:
        remove_optin(chat.id, user.id)
        await _reply(update, "🛑 You’ll no longer receive new-game alerts for this group.")

# ---------------- Trigger from /startgame ----------------
async def notify_on_new_game(
    context: ContextTypes.DEFAULT_TYPE,
    group_id: int,
    group_title: str | None = None,
    group_invite_link: str | None = None
):

    users = get_optins(group_id)
    if not users:
        return

    batch: list[str] = []
    BATCH_SIZE = 5

    for uid, name in users:
        batch.append(mention_html(uid, name))
        if len(batch) >= BATCH_SIZE:
            try:
                await context.bot.send_message(
                    chat_id=group_id,
                    text="🔔 New game starting! Notifying: " + ", ".join(batch),
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
            batch.clear()

    if batch:
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text="🔔 New game starting! Notifying: " + ", ".join(batch),
                parse_mode=ParseMode.HTML
            )
        except:
            pass

    title = group_title or "the group"

    try:
        group_link = group_invite_link or f"https://t.me/{(await context.bot.get_chat(group_id)).username}"
    except:
        group_link = group_invite_link or ""

    button = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚀 Join Now", url=group_link or "https://t.me/")]]
    )

    for uid, _ in users:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"🎮 A new game just started in <b>{title}</b>!\nClick below to join now:",
                parse_mode="HTML",
                reply_markup=button
            )
        except:
            pass

# ---------------- Registration ----------------
def notify_handlers(application):
    init_notify_db()
    application.add_handler(CommandHandler("notify", notify_cmd))
