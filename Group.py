import sqlite3
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from datetime import datetime, timedelta
from config import DB_PATH
import html

logger = logging.getLogger(__name__)

def group_stats_buttons():
    """Generate inline buttons for group stats categories."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Overview", callback_data="gstats_overview"),
            InlineKeyboardButton("🌟 Top Players", callback_data="gstats_top_players"),
        ],
        [
            InlineKeyboardButton("🕒 Activity", callback_data="gstats_activity"),
        ],
    ])

async def gstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show group-specific stats with buttons for detailed categories."""
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("❌ This command can only be used in groups.")
        return

    group_id = chat.id
    total_games = total_users = "N/A"

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Fetch group games played
        try:
            c.execute("SELECT games_played FROM groups WHERE group_id = ?", (group_id,))
            result = c.fetchone()
            total_games = result[0] if result else 0
        except Exception as e:
            logger.error(f"Error fetching total_games for group {group_id}: {e}")
            total_games = "N/A"

        # Fetch number of users in the group (assuming users are linked to groups via games_played)
        try:
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE games_played > 0")
            total_users = c.fetchone()[0]
        except Exception as e:
            logger.error(f"Error fetching total_users for group {group_id}: {e}")
            total_users = "N/A"

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
        logger.error(f"Critical error in gstats command for group {group_id}: {e}")
        await update.message.reply_text("❌ Critical error fetching group stats. Try again later.")

async def gstats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks for detailed group stats."""
    query = update.callback_query
    await query.answer()

    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await query.message.reply_text("❌ This command can only be used in groups.")
        return

    group_id = chat.id
    selected_category = query.data.replace("gstats_", "")

    # Check if the selected category is already displayed
    current_category = context.chat_data.get('current_gstats_category')
    if current_category == selected_category:
        logger.debug(f"User attempted to view same gstats category: {selected_category}")
        try:
            await query.message.reply_text("ℹ️ You're already viewing this stats category.")
        except Exception as e:
            logger.error(f"Error sending same-category message: {e}")
        return

    total_games = total_users = win_rate = active_users = total_eliminations = total_penalties = "N/A"
    top_players_info = most_recent_game = "N/A"

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Fetch group games played
        try:
            c.execute("SELECT games_played FROM groups WHERE group_id = ?", (group_id,))
            result = c.fetchone()
            total_games = result[0] if result else 0
        except Exception as e:
            logger.error(f"Error fetching total_games for group {group_id}: {e}")

        # Fetch total users (players with games_played > 0)
        try:
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE games_played > 0")
            total_users = c.fetchone()[0]
        except Exception as e:
            logger.error(f"Error fetching total_users for group {group_id}: {e}")

        # Fetch win rate (average of user win percentages)
        try:
            c.execute("SELECT SUM(wins), SUM(games_played) FROM users WHERE games_played > 0")
            sums = c.fetchone()
            total_wins = sums[0] or 0
            total_games_played = sums[1] or 0
            win_rate = (total_wins / total_games_played * 100) if total_games_played > 0 else 0
        except Exception as e:
            logger.error(f"Error fetching win_rate for group {group_id}: {e}")

        # Fetch active users (played in last 7 days)
        try:
            seven_days_ago = datetime.datetime.now() - timedelta(days=7)
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE updated_at >= ? AND games_played > 0", (seven_days_ago,))
            active_users = c.fetchone()[0]
        except Exception as e:
            logger.error(f"Error fetching active_users for group {group_id}: {e}")

        # Fetch total eliminations and penalties
        try:
            c.execute("SELECT SUM(eliminations), SUM(penalties) FROM users WHERE games_played > 0")
            sums = c.fetchone()
            total_eliminations = sums[0] or 0
            total_penalties = sums[1] or 0
        except Exception as e:
            logger.error(f"Error fetching eliminations/penalties for group {group_id}: {e}")

        # Fetch top 3 players
        try:
            c.execute("SELECT first_name, username, wins, total_score FROM users WHERE games_played > 0 ORDER BY wins DESC, total_score DESC LIMIT 3")
            top_players = c.fetchall()
            top_players_info = "\n".join(
                f"{i+1}. {html.escape(row[0] or 'N/A')} (@{html.escape(row[1] or 'N/A')}) - {row[2]} wins, {row[3]} score"
                for i, row in enumerate(top_players)
            ) if top_players else "No players with games yet."
        except Exception as e:
            logger.error(f"Error fetching top_players for group {group_id}: {e}")
            top_players_info = "N/A"

        # Fetch most recent game timestamp
        try:
            c.execute("SELECT MAX(updated_at) FROM users WHERE games_played > 0")
            result = c.fetchone()
            most_recent_game = result[0] if result and result[0] else "No recent games"
        except Exception as e:
            logger.error(f"Error fetching most_recent_game for group {group_id}: {e}")

        conn.close()

        # Prepare response based on category
        if selected_category == "overview":
            text = (
                "<b>Group Stats - Overview</b>\n\n"
                f"🏘 Group: {html.escape(chat.title or 'Unknown')}\n"
                f"🆔 ID: {group_id}\n"
                f"🎮 Games Played: {total_games}\n"
                f"👥 Players: {total_users}\n"
                f"🏆 Win Rate: {f'{win_rate:.1f}' if isinstance(win_rate, (int, float)) else 'N/A'}%"
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

        # Update message and store current category
        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=group_stats_buttons())
        context.chat_data['current_gstats_category'] = selected_category
        logger.debug(f"Displayed gstats category: {selected_category}")

    except Exception as e:
        logger.error(f"Critical error in gstats_callback for group {group_id}: {e}")
        await query.message.reply_text("❌ Critical error fetching group stats. Try again later.")

def register_handlers(app):
    """Register group stats command and callback handlers."""
    app.add_handler(CommandHandler("gstats", gstats))
    app.add_handler(CallbackQueryHandler(gstats_callback, pattern="^gstats_"))