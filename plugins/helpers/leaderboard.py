import math
import html
import asyncio
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import ContextTypes
from config import DB_PATH
from plugins.game.db import ensure_columns_exist
from plugins.utils.thumbnail import generate_card, download_user_photo_by_id

logger = logging.getLogger(__name__)

PER_PAGE = 5

# ---------------- DB ----------------
def get_all_users_sorted(limit: int = 100):
    try:
        ensure_columns_exist()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 
                user_id, 
                IFNULL(username, '') AS username, 
                IFNULL(first_name, '') AS first_name, 
                IFNULL(games_played, 0) AS games_played, 
                IFNULL(wins, 0) AS wins, 
                IFNULL(losses, 0) AS losses, 
                IFNULL(rounds_played, 0) AS rounds_played, 
                IFNULL(eliminations, 0) AS eliminations, 
                IFNULL(total_score, 0) AS total_score, 
                IFNULL(penalties, 0) AS penalties
            FROM users
            ORDER BY wins DESC, total_score DESC
            LIMIT ?
            """,
            (limit,),
        )
        result = cursor.fetchall()
        conn.close()
        return result
    except Exception:
        logger.exception("Error in get_all_users_sorted")
        return []

def get_user_rank(user_id):
    try:
        all_users = get_all_users_sorted()
        for idx, row in enumerate(all_users, start=1):
            if row['user_id'] == user_id:
                gp = row['games_played'] or 0
                win_percent = round((row['wins'] or 0) / gp * 100, 1) if gp > 0 else 0
                return {
                    "username": (row['username'] or row['first_name'] or "Unknown"),
                    "rank": idx,
                    "total_users": len(all_users),
                    "total_played": gp,
                    "wins": row['wins'] or 0,
                    "losses": row['losses'] or 0,
                    "win_percent": win_percent,
                    "rounds_played": row['rounds_played'] or 0,
                    "eliminations": row['eliminations'] or 0,
                    "total_score": row['total_score'] or 0,
                    "penalties": row['penalties'] or 0
                }
        # Not in list
        return {
            "username": "Unknown",
            "rank": len(all_users) + 1,
            "total_users": len(all_users),
            "total_played": 0,
            "wins": 0,
            "losses": 0,
            "win_percent": 0,
            "rounds_played": 0,
            "eliminations": 0,
            "total_score": 0,
            "penalties": 0
        }
    except Exception:
        logger.exception("Error in get_user_rank")
        return {
            "username": "Unknown", "rank": 1, "total_users": 0, "total_played": 0,
            "wins": 0, "losses": 0, "win_percent": 0, "rounds_played": 0,
            "eliminations": 0, "total_score": 0, "penalties": 0
        }

# ---------------- UI helpers ----------------
def _medal_for_rank(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "")

def _build_pager_old(page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    buttons = []
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◄ Previous", callback_data=f"leaderboard_{page-1}"))
    if page < total_pages:
        row.append(InlineKeyboardButton("Next ►", callback_data=f"leaderboard_{page+1}"))
    if row:
        buttons.append(row)

    row2 = [InlineKeyboardButton(f"Page {page}/{total_pages}", callback_data="lb:nop")]
    buttons.append(row2)
    return InlineKeyboardMarkup(buttons)

def _build_leaderboard_text(all_users, page: int, per_page: int, viewer_id: int) -> str:
    total = len(all_users)
    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total)

    text = "<b>──✦ Player Spotlight ✦──</b>\n\n"
    user_in_page = False

    for i, row in enumerate(all_users[start_idx:end_idx], start=start_idx + 1):
        rank = i
        medal = _medal_for_rank(rank)
        gp = row['games_played'] or 0
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        rounds_played = row['rounds_played'] or 0
        eliminations = row['eliminations'] or 0
        total_score = row['total_score'] or 0
        penalties = row['penalties'] or 0
        win_percent = round(wins / gp * 100, 1) if gp > 0 else 0
        display_name = html.escape(row['first_name'] or row['username'] or "Unknown")
        highlight = "⭐ " if row['user_id'] == viewer_id else ""

        text += f"{rank}. {medal} {highlight} <b>{display_name}</b> (ID: {row['user_id']})\n"
        text += f"   🎮 Games: {gp} | ⧉ Win%: {win_percent}\n"
        text += f"   🏆 Wins: {wins} | Lost: {losses}\n"
        text += f"   ⭐ Score: {total_score} | ⛔ Pen: {penalties}\n"
        text += "<b>────⊱◈◈◈⊰────</b>\n\n"

        if row['user_id'] == viewer_id:
            user_in_page = True

    if not user_in_page:
        me = get_user_rank(viewer_id)
        text += f"\n\n<b>────⊱◈◈◈⊰────</b>\n"
        text += "📌 <b>Your Rank:</b>\n"
        text += f"{me['rank']}. {html.escape(me['username'])} (ID: {viewer_id})\n"
        text += f"   🎮 Games: {me['total_played']} | ⧉ Win%: {me['win_percent']}\n"
        text += f"   🏆 Wins: {me['wins']} | Lost: {me['losses']}\n"
        text += f"   ⭐ Score: {me['total_score']} | ⛔ Pen: {me['penalties']}\n"

    return text, total_pages, page

# ---------------- Core flow ----------------
async def _send_leaderboard_initial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    viewer_id = update.effective_user.id
    all_users = get_all_users_sorted()
    text, total_pages, page = _build_leaderboard_text(all_users, page=1, per_page=PER_PAGE, viewer_id=viewer_id)
    pager = _build_pager_old(page, total_pages)

    top_user_id = all_users[0]['user_id'] if all_users else viewer_id
    try:
        usr_pfp_path = await download_user_photo_by_id(top_user_id, context.bot)
    except Exception:
        logger.exception("Failed to download top user's photo; using default card background.")
        usr_pfp_path = None

    try:
        card = generate_card("leaderboard", usr_pfp_path)
        await update.message.reply_photo(photo=card, caption=text, reply_markup=pager, parse_mode="HTML")
    except Exception:
        logger.exception("generate_card/send failed; falling back to text.")
        await update.message.reply_text(text=text, reply_markup=pager, parse_mode="HTML")


async def _edit_leaderboard_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query
    viewer_id = query.from_user.id
    all_users = get_all_users_sorted()
    text, total_pages, page = _build_leaderboard_text(all_users, page=page, per_page=PER_PAGE, viewer_id=viewer_id)
    pager = _build_pager_old(page, total_pages)

    try:
        if query.message.photo:
            await query.message.edit_caption(caption=text, reply_markup=pager, parse_mode="HTML")
        else:
            await query.message.edit_text(text=text, reply_markup=pager, parse_mode="HTML")
        await query.answer()
    except Exception as e:
        if "not modified" in str(e).lower():
            try: await query.answer("No changes.")
            except Exception: pass
        else:
            logger.exception("Error editing leaderboard caption; fallback to text.")
            try:
                await query.message.edit_text(
                    text=f"⚠️ Failed to update caption, showing text instead.\n\n{text}",
                    reply_markup=pager,
                    parse_mode="HTML",
                )
                await query.answer()
            except Exception:
                logger.exception("Fallback also failed for leaderboard caption update.")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # No scheduler; just send once with image, then caption-only edits.
    await _send_leaderboard_initial(update, context)

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = (query.data or "").strip()
    try:
        if not data.startswith("leaderboard_"):
            return await query.answer()
        page = int(data.split("_", 1)[1])
        await _edit_leaderboard_page(update, context, page)
    except (IndexError, ValueError):
        await query.answer()

async def users_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message and update.message.reply_to_message:
        user: User = update.message.reply_to_message.from_user

    else:
        user: User = update.effective_user

    user_id = user.id
    stats = get_user_rank(user_id)
    text = (
        f"🏆 𝐘𝐎𝐔𝐑 𝐑𝐀𝐍𝐊\n\n"
        f"{stats['rank']}. {stats['username']} \n"
        f"   🎮 Played: {stats['total_played']} |  Wins: {stats['wins']} |  Losses: {stats['losses']} |  Win %: {stats['win_percent']}\n"
        f"   🆔 {user_id}\n"
        "───────────────\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    mystic = await update.message.reply_text("🌸")

    if update.message and update.message.reply_to_message:
        user: User = update.message.reply_to_message.from_user

    elif context.args:
        arg = context.args[0]
        print(arg)
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, arg)
            user: User = member.user
        except Exception as e:
            print(e)
            user: User = update.effective_user
    else:
        user: User = update.effective_user

    stats = get_user_rank(user.id)
    ensure_columns_exist()
    import sqlite3
    conn = sqlite3.connect(__import__("config").DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT first_name, username,
               IFNULL(games_played,0),
               IFNULL(wins,0),
               IFNULL(losses,0),
               IFNULL(rounds_played,0),
               IFNULL(eliminations,0),
               IFNULL(total_score,0),
               IFNULL(last_score,0),
               IFNULL(penalties,0)
        FROM users
        WHERE user_id = ?
    """, (user.id,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("❌ No stats found. Play a game first!")
        return
    first_name, username, games_played, wins, losses, rounds_played, eliminations, total_score, last_score, penalties = row
    win_pct = (wins / games_played * 100) if games_played else 0
    display_name = f"@{username}" if username else first_name
    msg = f"""
╭━━━ ⟢ 𝗣𝗹𝗮𝘆𝗲𝗿 𝗦𝘁𝗮𝘁𝘀 ⟢ ━━━╮
┃ 👤 𝗡𝗮𝗺𝗲: <b>{first_name}</b>
╰━━━━━━━━━━━━━━━━━━━╯
🏆 𝐑𝐚𝐧𝐤: {stats['rank']}
🎮 <b>Games Played:</b> {games_played}
🥇 <b>Wins:</b> {wins} | <b>Losses:</b> {losses}
━━━━━━━━━━━━━━━━━━━━━
📊 <b>Win %:</b> {win_pct:.2f}%
⭐ <b>Total Score:</b> {total_score}
🎯 <b>Last Score:</b> {last_score}

☠️ <b>Eliminations:</b> {eliminations}
⛔ <b>Penalties:</b> {penalties}
━━━━━━━━━━━━━━━━━━━━━
💡 <i>One match doesn’t define you — the comeback will! 🚀</i>
"""

    try:
        usr_pfp_path = await download_user_photo_by_id(user.id, context.bot)
    except Exception:
        logger.exception("Failed to download top user's photo; using default card background.")
        usr_pfp_path = None

    await mystic.delete()
    try:
        card = generate_card("userinfo", usr_pfp_path)
        await update.message.reply_photo(photo=card, caption=msg, parse_mode="HTML")
    except Exception:
        logger.exception("generate_card/send failed; falling back to text.")
        await update.message.reply_text(text=msg, parse_mode="HTML")