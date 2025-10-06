import sqlite3
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from datetime import datetime, timedelta, timezone
from config import DB_PATH
import html

logger = logging.getLogger(__name__)

def group_stats_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Overview", callback_data="gstats_overview"),
            InlineKeyboardButton("🌟 Top Players", callback_data="gstats_top_players"),
        ],
        [ InlineKeyboardButton("🕒 Activity", callback_data="gstats_activity") ],
    ])

async def gstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ This command can only be used in groups.")
        return

    group_id = chat.id
    total_games = 0
    total_users = 0

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Per-group games played
        c.execute("SELECT COALESCE(games_played,0) FROM groups WHERE group_id=?", (group_id,))
        row = c.fetchone()
        total_games = row[0] if row else 0

        # Distinct players who have played in THIS group
        c.execute("""
            SELECT COUNT(DISTINCT user_id)
            FROM user_group_stats
            WHERE group_id=? AND games_played>0
        """, (group_id,))
        total_users = c.fetchone()[0] or 0

        conn.close()

        overview_text = (
            "<b>Group Statistics</b>\n\n"
            f"🏘 Group: {html.escape(chat.title or 'Unknown')}\n"
            f"🆔 ID: {group_id}\n"
            f"🎮 Games Played: {total_games}\n"
            f"👥 Players: {total_users}\n\n"
            "Select a category for details:"
        )

        await update.message.reply_text(overview_text, parse_mode="HTML", reply_markup=group_stats_buttons())
        context.chat_data['current_gstats_category'] = None

    except Exception as e:
        logger.exception(f"Critical error in gstats for group {group_id}: {e}")
        await update.message.reply_text("❌ Critical error fetching group stats. Try again later.")

async def gstats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await query.answer("❌ This command can only be used in groups.")
        return

    group_id = chat.id
    selected_category = query.data.replace("gstats_", "")

    current_category = context.chat_data.get('current_gstats_category')
    if current_category == selected_category:
        try:
            await query.answer("ℹ️ You're already viewing this stats category.")
        except Exception as e:
            logger.error(f"Same-category reply failed: {e}")
        return

    # Defaults
    total_games = total_users = 0
    win_rate = 0.0
    active_users = 0
    total_eliminations = total_penalties = 0
    top_players_info = "No players with games yet."
    most_recent_game = "No recent games"

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Overview
        c.execute("SELECT COALESCE(games_played,0), last_game_at FROM groups WHERE group_id=?", (group_id,))
        row = c.fetchone()
        if row:
            total_games = row[0] or 0
            most_recent_game = row[1] or "No recent games"

        c.execute("""
            SELECT COUNT(DISTINCT user_id)
            FROM user_group_stats
            WHERE group_id=? AND games_played>0
        """, (group_id,))
        total_users = c.fetchone()[0] or 0

        # Win rate = total wins / total games played (in this group)
        c.execute("""
            SELECT COALESCE(SUM(wins),0), COALESCE(SUM(games_played),0)
            FROM user_group_stats
            WHERE group_id=? AND games_played>0
        """, (group_id,))
        total_wins, total_gp = c.fetchone()
        win_rate = (total_wins / total_gp * 100.0) if total_gp > 0 else 0.0

        # Active users in last 7 days (based on updated_at, stored as UTC "YYYY-mm-dd HH:MM:SS")
        now_utc = datetime.now(timezone.utc)
        seven_days_ago = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            SELECT COUNT(DISTINCT user_id)
            FROM user_group_stats
            WHERE group_id=? AND updated_at IS NOT NULL AND updated_at >= ? AND games_played>0
        """, (group_id, seven_days_ago))
        active_users = c.fetchone()[0] or 0

        # Totals for eliminations/penalties
        c.execute("""
            SELECT COALESCE(SUM(eliminations),0), COALESCE(SUM(penalties),0)
            FROM user_group_stats
            WHERE group_id=? AND games_played>0
        """, (group_id,))
        total_eliminations, total_penalties = c.fetchone()

        # Top 3 players by wins then score within THIS group
        c.execute("""
            SELECT first_name, username, wins, total_score
            FROM user_group_stats
            WHERE group_id=? AND games_played>0
            ORDER BY wins DESC, total_score DESC
            LIMIT 3
        """, (group_id,))
        rows = c.fetchall()
        if rows:
            parts = []
            for i, (fn, un, w, sc) in enumerate(rows, start=1):
                name = html.escape(fn or "Player")
                at = f"@{html.escape(un)}" if un else ""
                parts.append(f"{i}. {name} {at} - {w} wins, {sc} score")
            top_players_info = "\n".join(parts)

        conn.close()

        # Compose output
        if selected_category == "overview":
            text = (
                "<b>Group Stats - Overview</b>\n\n"
                f"🏘 Group: {html.escape(chat.title or 'Unknown')}\n"
                f"🆔 ID: {group_id}\n"
                f"🎮 Games Played: {total_games}\n"
                f"👥 Players: {total_users}\n"
                f"🏆 Win Rate: {win_rate:.1f}%"
            )
        elif selected_category == "top_players":
            text = (
                "<b>Group Stats - Top Players</b>\n\n"
                f"🌟 Top 3 Players:\n{top_players_info}\n\n"
                f"⚠️ Total Penalties: {total_penalties}\n"
                f"☠️ Total Eliminations: {total_eliminations}"
            )
        elif selected_category == "activity":
            text = (
                "<b>Group Stats - Activity</b>\n\n"
                f"🕒 Active Players (7 days): {active_users}\n"
                f"📅 Last Game: {most_recent_game}\n"
                f"🎮 Total Games: {total_games}"
            )
        else:
            text = "❌ Unknown category"

        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=group_stats_buttons())
        context.chat_data['current_gstats_category'] = selected_category

    except Exception as e:
        logger.exception(f"Critical error in gstats_callback for group {group_id}: {e}")
        await query.answer("❌ Critical error fetching group stats. Try again later.")

