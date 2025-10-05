# helpers/leaderboard.py
import math
import html
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes
from config import DB_PATH
from plugins.game.db import ensure_columns_exist
import sqlite3

logger = logging.getLogger(__name__)

def get_all_users_sorted():
    try:
        ensure_columns_exist()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
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
            LIMIT 100
        """)
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
                win_percent = round(row['wins'] / row['games_played'] * 100, 1) if row['games_played'] > 0 else 0
                return {
                    "username": row['username'] or row['first_name'] or "Unknown",
                    "rank": idx,
                    "total_users": len(all_users),
                    "total_played": row['games_played'],
                    "wins": row['wins'],
                    "losses": row['losses'],
                    "win_percent": win_percent,
                    "rounds_played": row['rounds_played'],
                    "eliminations": row['eliminations'],
                    "total_score": row['total_score'],
                    "penalties": row['penalties']
                }
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

async def generate_leaderboard_task(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    user_id = update.effective_user.id
    all_users = get_all_users_sorted()
    per_page = 5
    total_pages = max(1, math.ceil(len(all_users) / per_page))
    page = max(1, min(page, total_pages))
    text = "<b>──✦ Player Spotlight ✦──</b>\n\n"
    user_in_page = False
    user_stats = None

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(all_users))

    for i, row in enumerate(all_users[start_idx:end_idx], start=start_idx + 1):
        games_played = row['games_played'] or 0
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        rounds_played = row['rounds_played'] or 0
        eliminations = row['eliminations'] or 0
        total_score = row['total_score'] or 0
        penalties = row['penalties'] or 0
        win_percent = round(wins / games_played * 100, 1) if games_played > 0 else 0
        display_name = html.escape(row['first_name'] or "Unknown")
        highlight = "⭐ " if row['user_id'] == user_id else ""
        text += "<b>────⊱◈◈◈⊰────</b>\n"
        text += f"{i}. {highlight}{display_name}\n"
        text += f"   ⧉ Win%: {win_percent} | 🎮 {games_played}\n"
        text += f"   🏆 {wins} | {losses} Lost\n"
        text += f"   🔄 Rounds: {rounds_played} | ☠️ Elim: {eliminations}\n"
        text += f"   ⭐ Score: {total_score} | ⛔ Pen: {penalties}\n"
        text += f"   ID: {row['user_id']}\n"
        if row['user_id'] == user_id:
            user_in_page = True
            user_stats = {
                "rank": i,
                "username": display_name,
                "total_played": games_played,
                "wins": wins,
                "losses": losses,
                "win_percent": win_percent,
                "rounds_played": rounds_played,
                "eliminations": eliminations,
                "total_score": total_score,
                "penalties": penalties
            }

    if not user_in_page:
        user_stats = get_user_rank(user_id)
        text += f"\n<b>────⊱◈◈◈⊰────</b>\n"
        text += f"📌 Your Rank:\n"
        text += f"{user_stats['rank']}. {html.escape(user_stats['username'])}\n"
        text += f"   ⧉ Win%: {user_stats['win_percent']} | 🎮 {user_stats['total_played']}\n"
        text += f"   🏆 {user_stats['wins']} | {user_stats['losses']} Lost\n"
        text += f"   🔄 Rounds: {user_stats['rounds_played']} | ☠️ Elim: {user_stats['eliminations']}\n"
        text += f"   ⭐ Score: {user_stats['total_score']} | ⛔ Pen: {user_stats['penalties']}\n"
        text += f"   ID: {user_id}\n"

    text += f"<b>────⊱◈◈◈⊰────</b>\nPage {page}/{total_pages}"

    keyboard = []
    if total_pages > 1:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("◄ Previous", callback_data=f"leaderboard_{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("Next ►", callback_data=f"leaderboard_{page+1}"))
        keyboard.append(buttons)

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    image_url = "https://graph.org/file/ca04194ed4b8b48eafcab-ab92ca372392f43809.jpg"

    try:
        if update.callback_query:
            await update.callback_query.message.edit_media(
                media=InputMediaPhoto(media=image_url, caption=text, parse_mode="HTML"),
                reply_markup=reply_markup
            )
            await update.callback_query.answer()
        else:
            await update.message.reply_photo(photo=image_url, caption=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        logger.exception("Error in generate_leaderboard_task")
        try:
            if update.callback_query:
                await update.callback_query.message.edit_text(text=f"⚠️ Failed to send leaderboard image, showing text instead.\n\n{text}", reply_markup=reply_markup, parse_mode="HTML")
                await update.callback_query.answer()
            else:
                await update.message.reply_text(text=f"⚠️ Failed to send leaderboard image, showing text instead.\n\n{text}", reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            logger.exception("Fallback also failed for leaderboard")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(generate_leaderboard_task(update, context, 1))

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data and query.data.startswith('leaderboard_'):
        try:
            page = int(query.data.split('_')[1])
            asyncio.create_task(generate_leaderboard_task(update, context, page))
        except (IndexError, ValueError):
            await query.answer()

async def users_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_rank(user_id)
    text = (
        f"🏆 𝐘𝐎𝐔𝐑 𝐑𝐀𝐍𝐊\n\n"
        f"{stats['rank']}. {stats['username']} \n"
        f"   🎮 Played: {stats['total_played']} |  Wins: {stats['wins']} |  Losses: {stats['losses']} |  Win %: {stats['win_percent']}\n"
        f"   🆔 {user_id}\n"
        "───────────────\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")
