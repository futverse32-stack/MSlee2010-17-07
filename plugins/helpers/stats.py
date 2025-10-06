import sqlite3
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from datetime import datetime, timedelta, timezone
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

        try:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_users: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM groups")
            total_groups = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_groups: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM games")
            total_games = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_games: %s", e)
            total_games = 0

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

    # Defaults
    total_users = total_groups = total_wins = total_losses = total_games = total_penalties = 0
    db_size_mb = storage_percentage = 0.0
    active_users = recent_games = avg_games_per_user = 0.0
    avg_score = 0.0
    top_players_info = "No players with wins yet."
    most_active_group_info = "No games played yet."
    inactive_users = 0
    win_rate = 0.0
    recent_registrations = 0

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()

        # Counts
        try:
            c.execute("SELECT COUNT(*) FROM users")
            total_users = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_users: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM groups")
            total_groups = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching total_groups: %s", e)

        # Sums
        try:
            c.execute("SELECT COALESCE(SUM(wins),0), COALESCE(SUM(losses),0), COALESCE(SUM(games_played),0), COALESCE(SUM(penalties),0) FROM users")
            total_wins, total_losses, total_games, total_penalties = c.fetchone()
        except Exception as e:
            logger.error("Error fetching user sums: %s", e)

        # DB size (assume 500 MB quota)
        try:
            db_size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
            db_size_mb = db_size_bytes / (1024 * 1024)
            storage_percentage = (db_size_mb / 500.0) * 100.0
        except Exception as e:
            logger.error("Error fetching DB size: %s", e)

        now_utc = datetime.now(timezone.utc)
        one_day_ago_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        seven_days_ago_str = (now_utc - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        # Active users (updated in last 7 days)
        try:
            c.execute("SELECT COUNT(DISTINCT user_id) FROM users WHERE updated_at IS NOT NULL AND updated_at >= ?", (seven_days_ago_str,))
            active_users = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching active_users: %s", e)

        # Recent games (24h)
        try:
            now_utc = datetime.now(timezone.utc)
            one_day_ago_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

            c.execute("SELECT COUNT(*) FROM games WHERE ended_at >= ?", (one_day_ago_str,))
            recent_games = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching recent_games: %s", e)

        # Avg games per user
        try:
            avg_games_per_user = (total_games / total_users) if total_users > 0 else 0.0
        except Exception as e:
            logger.error("Error calculating avg_games_per_user: %s", e)

        # Top players
        try:
            c.execute("SELECT first_name, username, wins FROM users ORDER BY wins DESC, total_score DESC LIMIT 3")
            rows = c.fetchall()
            if rows:
                lines = []
                for i, (first_name, username, wins) in enumerate(rows, start=1):
                    name = (first_name or "Player").replace("<","&lt;").replace(">","&gt;")
                    handle = f" (@{username})" if username else ""
                    lines.append(f"{i}. {name}{handle} - {wins} wins")
                top_players_info = "\n".join(lines)
            else:
                top_players_info = "No players with wins yet."
        except Exception as e:
            logger.error("Error fetching top_players: %s", e)
            top_players_info = "N/A"

        # Average score
        try:
            c.execute("SELECT COALESCE(AVG(total_score),0) FROM users")
            avg_score = c.fetchone()[0] or 0.0
        except Exception as e:
            logger.error("Error fetching avg_score: %s", e)

        # Most active group
        try:
            c.execute("SELECT title, group_id, games_played FROM groups ORDER BY games_played DESC LIMIT 1")
            most_active_group = c.fetchone()
            if most_active_group and (most_active_group[2] or 0) > 0:
                gtitle = (most_active_group[0] or "Unknown").replace("<","&lt;").replace(">","&gt;")
                most_active_group_info = f"{gtitle} (ID: {most_active_group[1]}, Games: {most_active_group[2]})"
            else:
                most_active_group_info = "No games played yet."
        except Exception as e:
            logger.error("Error fetching most_active_group: %s", e)
            most_active_group_info = "N/A"

        try:
            c.execute("SELECT COUNT(*) FROM users WHERE COALESCE(games_played,0) = 0")
            inactive_users = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching inactive_users: %s", e)

        try:
            win_rate = (total_wins / total_games * 100.0) if total_games > 0 else 0.0
        except Exception as e:
            logger.error("Error calculating win_rate: %s", e)

        try:
            c.execute("SELECT COUNT(*) FROM users WHERE created_at IS NOT NULL AND created_at >= ?", (seven_days_ago_str,))
            recent_registrations = c.fetchone()[0] or 0
        except Exception as e:
            logger.error("Error fetching recent_registrations: %s", e)

        conn.close()

        if selected_category == "bot":
            text = (
                "<b>Bot Stats</b>\n\n"
                f"💾 Storage: {db_size_mb:.2f} MB ({storage_percentage:.1f}% of 500 MB)\n"
                f"🎮 Total Games: {total_games}\n"
                f"🏆 Win Rate: {win_rate:.1f}%"
            )
        elif selected_category == "users":
            text = (
                "<b>User Stats</b>\n\n"
                f"👥 Total Users: {total_users}\n"
                f"🕒 Active Users (7 days): {active_users}\n"
                f"😴 Inactive Users: {inactive_users}\n"
                f"🆕 New Users (7 days): {recent_registrations}\n"
                f"🎮 Avg. Games/User: {avg_games_per_user:.1f}\n"
                f"📊 Avg. Score: {avg_score:.1f}"
            )
        elif selected_category == "groups":
            text = (
                "<b>Group Stats</b>\n\n"
                f"🏘 Total Groups: {total_groups}\n"
                f"🔥 Active Groups (24h): {recent_games}\n"
                f"🏆 Most Active Group: {most_active_group_info}"
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
