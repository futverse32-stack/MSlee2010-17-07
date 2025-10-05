# helpers/gstats.py
import sqlite3
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from datetime import datetime, timedelta
from config import DB_PATH
from plugins.connections.logger import setup_logger

logger = setup_logger(__name__)

def stats_buttons():
    """Generate inline buttons for stats categories."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Bot Stats", callback_data="stats_bot"),
            InlineKeyboardButton("👥 User Stats", callback_data="stats_users"),
        ],
        [
            InlineKeyboardButton("🏘 Group Stats", callback_data="stats_groups"),
            InlineKeyboardButton("🌟 Top Players", callback_data="stats_top_players"),
        ],
    ])

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_users = total_groups = total_games = "N/A"

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Fetch total users
        try:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching total_users: %s", e)
            total_users = "N/A"

        # Fetch total groups
        try:
            c.execute("SELECT COUNT(*) FROM groups")
            total_groups = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching total_groups: %s", e)
            total_groups = "N/A"

        # Fetch total games
        try:
            c.execute("SELECT SUM(games_played) FROM users")
            total_games = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_games: %s", e)
            total_games = "N/A"

        conn.close()

        overview_text = (
            "<b>Bot Statistics</b>\n\n"
            f"👥 Users: {total_users}\n"
            f"🏘 Groups: {total_groups}\n"
            f"🎮 Games Played: {total_games}\n\n"
            "Select a category for details:"
        )

        await update.message.reply_text(overview_text, parse_mode="HTML", reply_markup=stats_buttons())
        context.chat_data['current_stats_category'] = None

    except Exception as e:
        logger.exception("Critical error in stats command: %s", e)
        await update.message.reply_text("❌ Critical error fetching stats. Please try again later.")


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected_category = query.data.replace("stats_", "")
    current_category = context.chat_data.get('current_stats_category')
    if current_category == selected_category:
        try:
            await query.message.reply_text("ℹ️ You're already viewing this stats category.")
        except Exception:
            logger.debug("Couldn't notify same category")
        return

    total_users = total_groups = total_wins = total_losses = total_games = total_penalties = "N/A"
    db_size_mb = storage_percentage = active_users = recent_games = avg_games_per_user = "N/A"
    avg_score = top_players_info = most_active_group_info = inactive_users = win_rate = recent_registrations = "N/A"

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        try:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching total_users: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM groups")
            total_groups = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching total_groups: %s", e)

        try:
            c.execute("SELECT SUM(wins), SUM(losses), SUM(games_played), SUM(penalties) FROM users")
            sums = c.fetchone()
            total_wins = sums[0] or 0
            total_losses = sums[1] or 0
            total_games = sums[2] or 0
            total_penalties = sums[3] or 0
        except Exception as e:
            logger.error("Error fetching user sums: %s", e)

        try:
            db_size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
            db_size_mb = db_size_bytes / (1024 * 1024)
            storage_percentage = (db_size_mb / 500) * 100
        except Exception as e:
            logger.error("Error fetching DB size: %s", e)

        try:
            seven_days_ago = datetime.now() - timedelta(days=7)
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE updated_at >= ?", (seven_days_ago,))
            active_users = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching active_users: %s", e)

        try:
            one_day_ago = datetime.now() - timedelta(days=1)
            c.execute("SELECT COUNT(*) FROM users WHERE updated_at >= ? AND games_played > 0", (one_day_ago,))
            recent_games = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching recent_games: %s", e)

        try:
            avg_games_per_user = total_games / total_users if isinstance(total_users, int) and total_users > 0 else 0
        except Exception as e:
            logger.error("Error calculating avg_games_per_user: %s", e)

        try:
            c.execute("SELECT first_name, username, wins FROM users ORDER BY wins DESC LIMIT 3")
            top_players = c.fetchall()
            top_players_info = "\n".join(
                f"{i+1}. {row[0] or 'N/A'} (@{row[1] or 'N/A'}) - {row[2]} wins"
                for i, row in enumerate(top_players)
            ) if top_players else "No players with wins yet."
        except Exception as e:
            logger.error("Error fetching top_players: %s", e)
            top_players_info = "N/A"

        try:
            c.execute("SELECT AVG(total_score) FROM users")
            avg_score = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching avg_score: %s", e)

        try:
            c.execute("SELECT title, group_id, games_played FROM groups ORDER BY games_played DESC LIMIT 1")
            most_active_group = c.fetchone()
            most_active_group_info = (
                f"{most_active_group[0]} (ID: {most_active_group[1]}, Games: {most_active_group[2]})"
                if most_active_group and most_active_group[2] > 0 else "No games played yet."
            )
        except Exception as e:
            logger.error("Error fetching most_active_group: %s", e)
            most_active_group_info = "N/A"

        try:
            c.execute("SELECT COUNT(*) FROM users WHERE games_played = 0")
            inactive_users = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching inactive_users: %s", e)

        try:
            win_rate = (total_wins / total_games * 100) if isinstance(total_games, int) and total_games > 0 else 0
        except Exception as e:
            logger.error("Error calculating win_rate: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM users WHERE created_at >= ?", (seven_days_ago,))
            recent_registrations = c.fetchone()[0]
        except Exception as e:
            logger.error("Error fetching recent_registrations: %s", e)

        conn.close()

        # Prepare response based on button clicked
        if selected_category == "bot":
            text = (
                "<b>Bot Stats</b>\n\n"
                f"💾 Storage: {f'{db_size_mb:.2f}' if isinstance(db_size_mb, float) else 'N/A'} MB "
                f"({f'{storage_percentage:.1f}' if isinstance(storage_percentage, float) else 'N/A'}% of 500 MB)\n"
                f"🎮 Total Games: {total_games}\n"
                f"🏆 Win Rate: {f'{win_rate:.1f}' if isinstance(win_rate, (int, float)) else 'N/A'}%"
            )
        elif selected_category == "users":
            text = (
                "<b>User Stats</b>\n\n"
                f"👥 Total Users: {total_users}\n"
                f"🕒 Active Users (7 days): {active_users}\n"
                f"😴 Inactive Users: {inactive_users}\n"
                f"🆕 New Users (7 days): {recent_registrations}\n"
                f"🎮 Avg. Games/User: {f'{avg_games_per_user:.1f}' if isinstance(avg_games_per_user, (int, float)) else 'N/A'}\n"
                f"📊 Avg. Score: {f'{avg_score:.1f}' if isinstance(avg_score, (int, float)) else 'N/A'}"
            )
        elif selected_category == "groups":
            text = (
                "<b>Group Stats</b>\n\n"
                f"🏘 Total Groups: {total_groups}\n"
                f"🏆 Most Active Group: {most_active_group_info}\n"
                f"🎲 Recent Games (24h): {recent_games}"
            )
        elif selected_category == "top_players":
            text = (
                "<b>Top 3 Players</b>\n\n"
                f"{top_players_info}\n\n"
                f"⚠️ Total Penalties: {total_penalties}\n"
                f"🏆 Total Wins: {total_wins}\n"
                f"❌ Total Losses: {total_losses}"
            )
        else:
            text = "❌ Unknown category"

        await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=stats_buttons())
        context.chat_data['current_stats_category'] = selected_category
        logger.debug("Displayed stats category: %s", selected_category)

    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.debug("Message not modified for category %s", selected_category)
            try:
                await query.message.reply_text("ℹ️ You're already viewing this stats category.")
            except Exception:
                logger.debug("Can't send same-category message")
        else:
            logger.exception("BadRequest in stats_callback: %s", e)
            await query.message.reply_text("❌ Error updating stats. Try again later.")
    except Exception as e:
        logger.exception("Critical error in stats_callback: %s", e)
        await query.message.reply_text("❌ Critical error fetching stats. Try again later.")
