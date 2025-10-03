# game.py
import sqlite3
import asyncio
import math
from typing import Dict, Optional
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

from config import DB_PATH  # ensure DB_PATH exists in config.py

# -------------------- CONFIG --------------------
MIN_PLAYERS = 5
MAX_PLAYERS = 7      # new: maximum number of players
JOIN_TIME_SEC = 150
PICK_TIME_SEC = 120
       # Time for players to DM their pick each round
active_games: Dict[int, "MindScaleGame"] = {}   # group_id -> game instance
user_active_game: Dict[int, int] = {}           # user_id -> group_id (which group they're playing in)

# Placeholder file IDs for videos (replace with real Telegram file_ids or URLs)
VIDEO_ROUND_ANNOUNCE = "BAACAgUAAyEFAAS3OY5mAAIH_WjcAQai-HhFDKRdLmAMLxBm27m3AAJVHwAC00rhVpV-sXiybqzWNgQ"    # video shown at round start
VIDEO_ELIMINATION = "BAACAgUAAyEFAAS3OY5mAAIG_GjcAQWFyh2q8_qgBCE1qFRiIlLxAAJpHgAC00rhVgreiWfsIyY_NgQ"        # elimination video
VIDEO_WINNER = "BAACAgUAAyEFAAS3OY5mAAIG_mjcAQWjT5k0VtEounHroJd-hiHfAAJrHgAC00rhVrBRCwxYF9-UNgQ"              # winner video


# -------------------- DATABASE --------------------
def init_user_table():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            rounds_played INTEGER DEFAULT 0,
            eliminations INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            last_score INTEGER DEFAULT 0,
            penalties INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

def ensure_user_exists(user):
    """Insert user if not present"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
            (user.id, user.first_name, user.username),
        )
    else:
        c.execute(
            "UPDATE users SET first_name = ?, username = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user.first_name, user.username, user.id),
        )
    conn.commit()
    conn.close()

def update_user_after_game(user_id: int, score_delta: int, won: bool, rounds_played: int, eliminated: bool, penalties: int):
    """
    Update user stats at end of a match.
    score_delta: final score to add to total_score
    won: True if user won
    rounds_played: number of rounds user participated
    eliminated: True if eliminated
    penalties: total penalties to add
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # ensure row exists
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not c.fetchone():
        # if somehow absent, just create
        c.execute("INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?)", (user_id, "", ""))
    # update aggregated stats
    c.execute(
        """
        UPDATE users
        SET games_played = games_played + 1,
            wins = wins + ?,
            losses = losses + ?,
            rounds_played = rounds_played + ?,
            eliminations = eliminations + ?,
            total_score = total_score + ?,
            penalties = penalties + ?,
            last_score = ?
        WHERE user_id = ?
        """,
        (1 if won else 0, 0 if won else 1, rounds_played, 1 if eliminated else 0, score_delta, penalties, score_delta, user_id)
    )
    conn.commit()
    conn.close()

def ensure_columns_exist():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    required_columns = {
        "games_played": "INTEGER DEFAULT 0",
        "wins": "INTEGER DEFAULT 0",
        "losses": "INTEGER DEFAULT 0",
        "rounds_played": "INTEGER DEFAULT 0",
        "eliminations": "INTEGER DEFAULT 0",
        "total_score": "INTEGER DEFAULT 0",
        "last_score": "INTEGER DEFAULT 0",
        "penalties": "INTEGER DEFAULT 0"
    }

    # Get existing columns
    c.execute("PRAGMA table_info(users)")
    existing_columns = [col[1] for col in c.fetchall()]

    # Add missing columns
    for col, col_type in required_columns.items():
        if col not in existing_columns:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")

    conn.commit()
    conn.close()

# -------------------- GAME DATA CLASSES --------------------
class Player:
    def __init__(self, user_id: int, name: str, username: Optional[str] = None):
        self.user_id: int = user_id
        self.name: str = name
        self.username: Optional[str] = username
        self.current_number: Optional[int] = None      # number picked this round
        self.score: int = 0                             # current score
        self.eliminated: bool = False                  # is player eliminated
        self.miss_offenses: int = 0                    # times player missed pick
        self.total_penalties: int = 0                  # total penalties accrued
        self.rounds_played: int = 0                    # number of rounds played

    def __repr__(self):
        return f"<Player {self.name} ({self.user_id}) score={self.score} eliminated={self.eliminated}>"

# In the MindScaleGame class (replace the existing class definition)
class MindScaleGame:
    def __init__(self, group_id: int):
        self.group_id: int = group_id
        self.players: Dict[int, Player] = {}           # user_id -> Player
        self.join_phase_active: bool = True
        self.round_number: int = 0
        self.current_round_active: bool = False
        self.pick_tasks: Dict[int, asyncio.Task] = {}      # user_id -> asyncio.Task for pick timeout
        self.pick_30_alerts: Dict[int, asyncio.Task] = {}  # user_id -> asyncio.Task for 30s alert
        self.score_history: list = []                      # list of per-round results
        self.join_timer_task: Optional[asyncio.Task] = None # Track join phase timer task

    @property
    def active_players(self):
        """Return list of players who are not eliminated."""
        return [p for p in self.players.values() if not p.eliminated]

    def add_player(self, user):
        """Add player to game."""
        if user.id not in self.players:
            p = Player(user.id, user.full_name, getattr(user, "username", None))
            self.players[user.id] = p
            user_active_game[user.id] = self.group_id

    def remove_player(self, user_id: int):
        """Remove player from game."""
        if user_id in self.players:
            del self.players[user_id]
        user_active_game.pop(user_id, None)

    def reset_round_picks(self):
        """Reset current picks for a new round."""
        for p in self.players.values():
            p.current_number = None

# -------------------- HELPERS --------------------
def mention_html(p: Player):
    return f"<a href='tg://user?id={p.user_id}'>{p.name}</a>"

# -------------------- START ROUND (NEX STYLE) --------------------
async def start_round(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]

    if game.current_round_active:
        return

    # Initialize round
    game.current_round_active = True
    game.round_number += 1
    game.reset_round_picks()
    game.round_results_sent = False

    # Cancel old tasks
    for t in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        t.cancel()
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    # -------------------- Countdown --------------------
    try:
        msg: Message = await context.bot.send_message(
            chat_id=group_id,
            text=f" 𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n\n🎲 Begins in 5..."
        )
    except:
        msg = None

    async def countdown():
        for sec in [4, 3, 2, 1]:
            await asyncio.sleep(1)  # ⏳ backgrounded countdown
            if msg:
                try:
                    await msg.edit_text(
                        f" 𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n\n🎲 Begins in {sec}..."
                    )
                except:
                    pass
        await asyncio.sleep(1)
        if msg:
            try:
                await msg.edit_text(
                    f" �_R𝗼𝘂𝗻𝗱 {game.round_number} \n\n🎲 Starting now! Check your DMs and send a number (0–100)."
                )
            except:
                pass

    # 🔹 Run countdown fully in background so it doesn't block other groups
    asyncio.create_task(countdown())

    # -------------------- Announcement with Video/Button --------------------
    bot_username = (await context.bot.get_me()).username or ""
    dm_url = f"https://t.me/{bot_username}"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Send number in DM", url=dm_url)]])
    try:
        if VIDEO_ROUND_ANNOUNCE and VIDEO_ROUND_ANNOUNCE != "VIDEO_FILE_ID_ROUND":
            await context.bot.send_video(
                chat_id=group_id,
                video=VIDEO_ROUND_ANNOUNCE,
                caption=f" 𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Send your number in DM!",
                reply_markup=buttons
            )
        else:
            await context.bot.send_message(
                chat_id=group_id,
                text=f" 𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Send your number in DM!",
                reply_markup=buttons
            )
    except:
        await context.bot.send_message(
            chat_id=group_id,
            text=f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} \n🎲 Send your number in DM!",
            reply_markup=buttons
        )

    # -------------------- Check active players --------------------
    players = game.active_players
    if not players:
        await context.bot.send_message(chat_id=group_id, text="❌ No active players. Ending game.")
        await end_game(context, group_id)
        return

    # -------------------- Per-player DM and timers --------------------
    async def handle_miss(user_id: int):
        p = game.players.get(user_id)
        if not p or p.eliminated or p.current_number is not None:
            return

        # ---------------- Penalty logic ----------------
        if getattr(p, "timeout_count", 0) == 0:
            p.score -= 1
            p.total_penalties += 1
            p.timeout_count = 1
            p.current_number = "Skipped"
            try:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"⚠️ {mention_html(p)} did not respond in time! -2 penalty.",
                    parse_mode="HTML"
                )
            except:
                pass
        else:
            p.eliminated = True
            try:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"☠️ {mention_html(p)} failed again and is eliminated!",
                    parse_mode="HTML"
                )
            except:
                pass

        # Remove tasks
        game.pick_tasks.pop(user_id, None)
        game.pick_30_alerts.pop(user_id, None)

        # Check if round can be processed
        if all(pl.current_number is not None or pl.eliminated for pl in game.active_players):
            game.current_round_active = False
            await process_round_results(context, group_id)

    async def send_30_alert(user_id: int):
        p = game.players.get(user_id)
        if not p or p.eliminated or p.current_number is not None:
            return
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=f"⏳ {mention_html(p)} — 30 seconds left to send your number in DM!",
                parse_mode="HTML"
            )
        except:
            pass

    # -------------------- Send DMs and start timers --------------------
    for p in players:
        # DM instructions
        try:
            await context.bot.send_message(
                chat_id=p.user_id,
                text=f"🎯  𝗥𝗼𝘂𝗻𝗱 {game.round_number} \nSend a number between 0–100 (plain message)."
            )
        except:
            await context.bot.send_message(
                chat_id=group_id,
                text=f"⚠️ Could not DM {mention_html(p)}. Please open your DM with the bot.",
                parse_mode="HTML"
            )

        # 30-second alert
        async def _alert(uid=p.user_id):
            await asyncio.sleep(PICK_TIME_SEC - 30)
            await send_30_alert(uid)
        t30 = asyncio.create_task(_alert())
        game.pick_30_alerts[p.user_id] = t30

        # Full timeout
        async def _timeout(uid=p.user_id):
            await asyncio.sleep(PICK_TIME_SEC)
            await handle_miss(uid)
        t_timeout = asyncio.create_task(_timeout())
        game.pick_tasks[p.user_id] = t_timeout
        
async def process_round_results(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]

    # Prevent duplicate processing
    if getattr(game, "round_results_sent", False):
        return
    game.round_results_sent = True

    # Gather valid picks
    picks = [(p.user_id, p.current_number) for p in game.active_players 
             if isinstance(p.current_number, (int, float))]

    if not picks:
        await context.bot.send_message(chat_id=group_id, text="❌ No valid picks received this round.")
        await end_game(context, group_id)
        return

    nums = [n for _, n in picks]
    average = sum(nums) / len(nums)
    target = average * 0.8

    alive_players = [p for p in game.players.values() if not p.eliminated]

    # -------------------- Reveal picks --------------------
    reveal_text = "𝗥𝗼𝘂𝗻𝗱 𝗣𝗶𝗰𝗸𝘀 \n\n"
    for p in game.active_players:
        pick_val = p.current_number if p.current_number is not None else "⏳ Skipped"
        reveal_text += f"♦️ {mention_html(p)} → {pick_val}\n"
    reveal_text += "▭▭▭▭▭▭▭▭▭▭▭▭▭▭"
    try:
        await context.bot.send_message(chat_id=group_id, text=reveal_text, parse_mode="HTML")
        await asyncio.sleep(2)  # Await here if you want a blocking delay; otherwise, task it.
    except:
        pass

    # -------------------- Duplicate Penalty --------------------
    num_alive = len(alive_players)
    duplicate_players = set()
    duplicates_exist = False

    # ✅ Apply duplicates only if more than 2 alive AND at least 1 player has already been eliminated
    num_eliminated = len([p for p in game.players.values() if p.eliminated])
    if num_alive > 2 and num_eliminated >= 1:
        counts = {}
        for uid, num in picks:
            counts[num] = counts.get(num, 0) + 1
        duplicate_nums = {num for num, count in counts.items() if count > 1}
        if duplicate_nums:
            duplicates_exist = True
        for p in game.active_players:
            if p.current_number in duplicate_nums:
                duplicate_players.add(p)
                p.score -= 1
                p.total_penalties += 1
                try:
                    await context.bot.send_message(
                        chat_id=group_id,
                        text=f"⚠️ {mention_html(p)} picked a duplicate number! -1 point penalty.",
                        parse_mode="HTML"
                    )
                except:
                    pass

    # -------------------- Closest number logic --------------------
    winner_players = []
    diffs = [(p, abs(p.current_number - target)) for p in alive_players 
             if isinstance(p.current_number, (int, float))]
    if diffs:
        min_diff = min(d for _, d in diffs)
        winner_players = [p for p, d in diffs if d == min_diff and not p.eliminated]

    # -------------------- Special case: 0 vs 100 --------------------
    alive_now = [p for p in game.players.values() if not p.eliminated]
    zero_vs_hundred_case = False
    if len(alive_now) == 2:
        vals = [p.current_number for p in alive_now if isinstance(p.current_number, (int, float))]
        if 0 in vals and 100 in vals:
            p100 = next(p for p in alive_now if p.current_number == 100)
            winner_players = [p100]
            zero_vs_hundred_case = True
            for p in alive_now:
                if p != p100 and p not in duplicate_players:
                    p.score -= 1
                    p.total_penalties += 1

    # -------------------- Second elimination special penalty --------------------
    special_penalty_applied = False
    if num_eliminated >= 2 and not zero_vs_hundred_case and not duplicates_exist:
        exact_target_players = [p for p in alive_players if p.current_number == round(target)]
        if exact_target_players:
            winner_players = exact_target_players
            special_penalty_applied = True
            for p in alive_players:
                if p not in winner_players and p not in duplicate_players:
                    p.score -= 2
                    p.total_penalties += 2

    # -------------------- Apply non-winner penalties --------------------
    if not zero_vs_hundred_case:
        for p in alive_players:
            if p in duplicate_players:
                continue  # duplicates already penalized
            if p not in winner_players:
                # ✅ Skip non-winner penalty if player already got -2 (timeout)
                if getattr(p, "timeout_penalty_applied", False):
                    continue
                if duplicates_exist:
                    continue  # non-duplicate players are safe when duplicates exist
                if special_penalty_applied:
                    continue
                else:
                    p.score -= 1
                    p.total_penalties += 1

    # -------------------- Elimination check --------------------
    eliminated_now = []
    for p in list(game.players.values()):
        if not p.eliminated and p.score <= -10:
            p.eliminated = True
            eliminated_now.append(p)

    # -------------------- Round Results Announcement --------------------
    res = f"𝗥𝗼𝘂𝗻𝗱 {game.round_number} 𝗥𝗲𝘀𝘂𝗹𝘁𝘀 \n\n"
    res += f"🎯 Target: {target:.2f}\n\n"

    if winner_players:
        winner_names = ", ".join([mention_html(p) for p in winner_players if not p.eliminated])
        if winner_names:
            res += f"👑 Winner{'s' if len(winner_players) > 1 else ''}: {winner_names}\n\n"

    res += "📊 Scores:\n"
    for p in sorted(game.players.values(), key=lambda x: -x.score):
        status = " (Eliminated)" if p.eliminated else ""
        res += f"♦️ {mention_html(p)} — {p.score}{status}\n"

    res += " Keep pushing, the next round awaits! 🚀"
    try:
        await context.bot.send_message(chat_id=group_id, text=res, parse_mode="HTML")
        await asyncio.sleep(5)
    except:
        pass

    # -------------------- Play elimination videos --------------------
    for p in eliminated_now:
        try:
            await context.bot.send_video(
                chat_id=group_id,
                video=VIDEO_ELIMINATION,
                caption=f"☠️ {mention_html(p)} you are Eliminated!",
                parse_mode="HTML"
            )
        except:
            pass

    # -------------------- End game if ≤1 left --------------------
    alive_now = [p for p in game.players.values() if not p.eliminated]
    if len(alive_now) <= 1:
        await end_game(context, group_id)
        return

    # -------------------- Reset round and start next --------------------
    game.current_round_active = False
    game.round_results_sent = False
    game.reset_round_picks()
    for task in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        task.cancel()
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    # Start next round (already backgrounded)
    asyncio.create_task(start_round(context, group_id))
# -------------------- DM PICK HANDLER --------------------
async def dm_pick_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles private number submissions (0-100) for active game rounds.
    Validates input, updates the user's pick, and proceeds if all players have picked.
    """
    user = update.effective_user
    if not user:
        return

    # Check if user is in an active game
    if user.id not in user_active_game:
        await update.message.reply_text(
            "♦ You are not currently participating in any active game."
        )
        return

    group_id = user_active_game[user.id]
    if group_id not in active_games:
        await update.message.reply_text(
            "⚠️ The game you were in no longer exists."
        )
        user_active_game.pop(user.id, None)
        return

    game = active_games[group_id]

    # Check if a round is active
    if not getattr(game, "current_round_active", False):
        await update.message.reply_text(
            "⏳ There is no active round at the moment. Please wait for the next round to start."
        )
        return

    # Validate input
    text = (update.message.text or "").strip()
    if not text.isdigit():
        await update.message.reply_text(
            "♦ Invalid input. Please send a **plain number between 0 and 100** "
        )
        return

    num = int(text)
    if not 0 <= num <= 100:
        await update.message.reply_text(
            "⚠️ Your number must be between 0 and 100. Please try again."
        )
        return

    # Ensure player exists and is active
    if user.id not in game.players:
        await update.message.reply_text(
            "♦ You are not listed as a player in this game."
        )
        return

    player = game.players[user.id]
    if getattr(player, "eliminated", False):
        await update.message.reply_text(
            "☠️ You have been eliminated and cannot participate in this round."
        )
        return

    if getattr(player, "current_number", None) is not None:
        await update.message.reply_text(
            "♦ You have already submitted a number for this round."
        )
        return

    # Accept the pick
    player.current_number = num

    # --- NEW: send DM reply with a button to go back to the group ---
    try:
        group_link = f"https://t.me/c/{str(group_id)[4:]}"
    except Exception:
        group_link = None

    if group_link:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Game", url=group_link)]]
        )
        await update.message.reply_text(
            f"♦ Number received: <b>{num}</b>\n"
            "🎯 Get ready for the next round!",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    else:
        # fallback if something odd with group_id
        await update.message.reply_text(
            f"♦ Number received: <b>{num}</b>\n"
            "🎯 Get ready for the next round!",
            parse_mode="HTML"
        )

    # Cancel any existing pick timeout or 30s alert
    task = game.pick_tasks.pop(user.id, None)
    if task and not task.done():
        task.cancel()
    task30 = game.pick_30_alerts.pop(user.id, None)
    if task30 and not task30.done():
        task30.cancel()

    # If all players have picked, process results immediately
    if all((pl.current_number is not None or getattr(pl, "eliminated", False)) for pl in game.players.values()):
        # Cancel remaining per-player tasks safely
        for t in list(game.pick_tasks.values()):
            if t and not t.done():
                t.cancel()
        for t in list(game.pick_30_alerts.values()):
            if t and not t.done():
                t.cancel()

        game.pick_tasks.clear()
        game.pick_30_alerts.clear()

        # Process round results immediately
        await process_round_results(context, group_id)

# -------------------- END GAME --------------------
async def end_game(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    """
    Finalize the match: send final scoreboard in Nex-style, announce winner,
    save user stats, cancel tasks, and clean active game data.
    """
    if group_id not in active_games:
        return
    game = active_games[group_id]

    # Prevent duplicate end_game call
    if getattr(game, "ended", False):
        return
    game.ended = True

    # -------------------- Final Scoreboard (Nex Style) --------------------
    players_sorted = sorted(game.players.values(), key=lambda p: -getattr(p, "score", 0))
    text = "『 𝗙𝗶𝗻𝗮𝗹 𝗦𝗰𝗼𝗿𝗲𝗰𝗮𝗿𝗱 』\n"
    text += "🎖️ Top Scorers:\n"

    for p in players_sorted:
        name = getattr(p, "name", "Unknown")
        user_id = getattr(p, "user_id", None)
        score = getattr(p, "score", 0)
        status = " (Out)" if getattr(p, "eliminated", False) else ""
        text += f"♦️  <a href='tg://user?id={user_id}'>{name}</a> — {score}  {status}\n"

    text += "\n⊱⋅ ──────────────── ⋅⊰\n\n"

    # -------------------- Winner Announcement --------------------
    winners = [p for p in players_sorted if not getattr(p, "eliminated", False)]
    winner = winners[0] if winners else (players_sorted[0] if players_sorted else None)

    if winner:
        winner_name = getattr(winner, "name", "Unknown")
        winner_id = getattr(winner, "user_id", None)
        text += f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆\n"

    # -------------------- Send Scorecard --------------------
    try:
        await context.bot.send_message(chat_id=group_id, text=text, parse_mode="HTML")
    except Exception:
        pass

    # -------------------- Winner Video (Mandatory if set) --------------------
    if winner and VIDEO_WINNER and VIDEO_WINNER != "VIDEO_FILE_ID_WIN":
        try:
            await context.bot.send_video(
                chat_id=group_id,
                video=VIDEO_WINNER,
                caption=f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆",
                parse_mode="HTML"
            )
        except Exception:
            # If video cannot be sent (e.g., restrictions), just send text only
            try:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=f"🎉 Champion: <a href='tg://user?id={winner_id}'>{winner_name}</a> 🏆",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    # -------------------- Save User Stats --------------------
    for p in game.players.values():
        try:
            user_obj = type("U", (), {
                "id": getattr(p, "user_id", None),
                "first_name": getattr(p, "name", "Unknown"),
                "username": getattr(p, "username", None)
            })
            ensure_user_exists(user_obj)
            update_user_after_game(
                user_id=getattr(p, "user_id", None),
                score_delta=getattr(p, "score", 0),
                won=(winner is not None and getattr(p, "user_id", None) == getattr(winner, "user_id", None)),
                eliminated=getattr(p, "eliminated", False),
                rounds_played=getattr(p, "rounds_played", 0),
                penalties=getattr(p, "total_penalties", 0)
            )
        except Exception:
            continue

    # -------------------- Clean Active Game Data --------------------
    for p in game.players.values():
        user_active_game.pop(getattr(p, "user_id", None), None)

    # Cancel pending async tasks safely
    for t in list(getattr(game, "pick_tasks", {}).values()):
        if t and not t.done():
            t.cancel()
    for t in list(getattr(game, "pick_30_alerts", {}).values()):
        if t and not t.done():
            t.cancel()

    # Clear task references
    getattr(game, "pick_tasks", {}).clear()
    getattr(game, "pick_30_alerts", {}).clear()

    # Remove game from active_games
    active_games.pop(group_id, None)

    # ✅ Notify group ready for new game
    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=" The game has ended. You can start a new game anytime with /startgame."
        )
    except Exception:
        pass

# -------------------- LOBBY HANDLERS (start/join/leave/players/endmatch) --------------------
async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        await update.message.reply_text("❌ /startgame can only be used in groups!")
        return
    group_id = update.effective_chat.id
    if group_id in active_games:
        await update.message.reply_text("❌ A game is already running in this group.")
        return

    # Send photo with mode selection buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Solo", callback_data=f"start_solo:{group_id}"),
            InlineKeyboardButton("Team", callback_data=f"start_team:{group_id}")
        ]
    ])
    await update.message.reply_photo(
        photo="https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg",
        caption="🎲 Mind Scale Game\n\nChoose game mode:",
        reply_markup=buttons
    )

# -------------------- MODE SELECTION HANDLER --------------------
async def mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split(":")
    if len(data) != 2:
        return
    mode, group_id = data[0], int(data[1])

    if mode == "start_solo":
        if group_id in active_games:
            await query.edit_message_caption(
                caption="❌ A game is already running in this group."
            )
            return
        game = MindScaleGame(group_id)
        active_games[group_id] = game
        welcome_text = f"""🎲 Mind Scale Game Starting (Solo Mode) 🎲

Use /join to join the current game
Use /leave to leave before the {JOIN_TIME_SEC // 60}-min timer ends

Minimum players: {MIN_PLAYERS}"""
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🛠 Support", url="https://t.me/NexoraBots_Support")]])
        await query.edit_message_caption(
            caption=welcome_text,
            reply_markup=buttons
        )
        # Start join timer task (non-blocking)
        asyncio.create_task(join_phase_scheduler(context, group_id))

    elif mode == "start_team":
        await query.edit_message_caption(
            caption="🚀 Team Mode is coming soon! Try Solo Mode for now.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Play Solo", callback_data=f"start_solo:{group_id}")]
            ])
        )

# Modify join_phase_scheduler to store the task in the game object
async def join_phase_scheduler(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    """Schedule 60s/30s/10s alerts AND join end, non-blocking."""
    if group_id not in active_games:
        return
    game = active_games[group_id]

    # Schedule alerts in parallel
    async def schedule_alert(delay, seconds_left):
        await asyncio.sleep(delay)
        if group_id in active_games and active_games[group_id].join_phase_active:
            await context.bot.send_message(chat_id=group_id, text=f"⏱ Hurry up! Only {seconds_left} seconds left to /join the game!")

    tasks = []
    for sec in [60, 30, 10]:
        delay = max(0, JOIN_TIME_SEC - sec)
        tasks.append(asyncio.create_task(schedule_alert(delay, sec)))

    # Store the join timer task
    game.join_timer_task = asyncio.create_task(asyncio.sleep(JOIN_TIME_SEC))

    # Wait for full join period
    try:
        await game.join_timer_task
    except asyncio.CancelledError:
        pass  # Handle cancellation gracefully

    # End join phase
    if group_id in active_games:
        await end_join_phase(context, group_id)

    # Cleanup
    for t in tasks:
        if not t.done():
            t.cancel()
async def end_join_phase(context: ContextTypes.DEFAULT_TYPE, group_id: int):
    if group_id not in active_games:
        return
    game = active_games[group_id]

    # ✅ Mark join phase as inactive
    game.join_phase_active = False

    num_joined = len(game.players)

    if num_joined < 5:  # MIN_PLAYERS
        await context.bot.send_message(
            chat_id=group_id,
            text=f"❌  𝗝𝗼𝗶𝗻 𝗣𝗵𝗮𝘀𝗲 𝗘𝗻𝗱𝗲𝗱』\n\n"
                 f"🚫 Not enough players joined ({num_joined}/5).\n"
                 f"The game has been canceled.",
            parse_mode="HTML"
        )
        for p in game.players.values():
            user_active_game.pop(p.user_id, None)
        del active_games[group_id]
        return

    # If more than MAX_PLAYERS, take only first 7
    if num_joined > 7:
        joined_players = list(game.players.values())[:7]
        removed_players = list(game.players.values())[7:]
        game.players = {p.user_id: p for p in joined_players}

        # Inform removed players
        for p in removed_players:
            await context.bot.send_message(
                chat_id=p.user_id,
                text="⚠️ Sorry! The match can only have 7 players. You won't be playing this round.",
            )

    players_list = "\n".join(
        [f"♦️ <a href='tg://user?id={p.user_id}'>{p.name}</a>" for p in game.players.values()]
    )

    await context.bot.send_message(
        chat_id=group_id,
        text=(
            f"『 𝗠𝗮𝘁𝗰𝗵 𝗦𝗲𝘁𝘁𝗹𝗲𝗱 』\n\n"
            f"🎲 Players Joined ({len(game.players)}):\n"
            f"{players_list}\n\n"
            f"⊱⋅ ─────────── ⋅⊰\n\n"
            f"✧ Brace yourselves! The game is about to begin! 🚀"
        ),
        parse_mode="HTML"
    )

    # Start the game immediately
    await start_round(context, group_id)

# ---------------- JOIN ----------------
async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ Use /join in the group where the game is running."
        )
        return

    group_id = update.effective_chat.id
    user = update.effective_user

    # Check if user is already in a game
    if user.id in user_active_game:
        gid = user_active_game[user.id]
        await update.message.reply_text(
            f" ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ You are already playing in another group (`{gid}`). Finish it first!",
            parse_mode="Markdown"
        )
        return

    # Check if a game exists in this group
    if group_id not in active_games:
        await update.message.reply_text(
            " ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ No active game. Start one with /startgame"
        )
        return

    game = active_games[group_id]

    # Check if join phase is active
    if not getattr(game, "join_phase_active", False):
        await update.message.reply_text(
            " ⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ Join phase is already closed!"
        )
        return

    # Check if max players reached
    if len(getattr(game, "players", [])) >= MAX_PLAYERS:
        await update.message.reply_text(
            f"⚠️ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n❌ The game already has {MAX_PLAYERS} players. Cannot join."
        )
        return

    # Ensure user exists in stats
    ensure_user_exists(user)

    # Add player to game
    game.add_player(user)

    await update.message.reply_text(
        f" ✅ 𝗝𝗼𝗶𝗻 𝗚𝗮𝗺𝗲 \n\n✨ <b>{user.full_name}</b> joined the match!",
        parse_mode="HTML"
    )

    # ---------------- START IMMEDIATELY WHEN FULL ----------------
    if len(game.players) == MAX_PLAYERS:
        # Cancel join timer if still running
        join_timer = getattr(game, "join_timer_task", None)
        if join_timer and not join_timer.done():
            join_timer.cancel()
            game.join_timer_task = None

        # Mark join phase ended and start the game immediately
        game.join_phase_active = False
        game.game_started = True

        await context.bot.send_message(
            chat_id=group_id,
            text=f" 🚀 𝗠𝗮𝘁𝗰𝗵 𝗦𝘁𝗮𝗿𝘁 \n\n✅ {MAX_PLAYERS} players joined! Starting immediately..."
        )
        await start_round(context, group_id)

# ---------------- LEAVE ----------------
async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            " ⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲\n\n❌ Use /leave in the group."
        )
        return

    group_id = update.effective_chat.id
    user_id = update.effective_user.id

    if group_id not in active_games:
        await update.message.reply_text(
            "⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n❌ No active game."
        )
        return

    game = active_games[group_id]

    if not game.join_phase_active:
        await update.message.reply_text(
            "⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n❌ You cannot leave after the match has started."
        )
        return

    if user_id not in game.players:
        await update.message.reply_text(
            " ⚠️ 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲\n\n❌ You are not part of this game."
        )
        return

    game.remove_player(user_id)

    await update.message.reply_text(
        f" 👋 𝗟𝗲𝗮𝘃𝗲 𝗚𝗮𝗺𝗲 \n\n🚪 <b>{update.effective_user.full_name}</b> has left the match.",
        parse_mode="HTML"
    )

# ---------------- PLAYERS LIST ----------------
async def players(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if group_id not in active_games:
        await update.message.reply_text(
            "『 ⚠️ 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 𝗟𝗶𝘀𝘁 』\n\n❌ No active game found."
        )
        return

    game = active_games[group_id]
    if not game.players:
        await update.message.reply_text(
            "『 ⚠️ 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 �_L𝗶𝘀𝘁 』\n\n❌ No players joined yet."
        )
        return

    # Build player list
    text = " 🎲 𝗖𝘂𝗿𝗿𝗲𝗻𝘁 𝗣𝗹𝗮𝘆𝗲𝗿𝘀 🎲 \n\n"
    for i, p in enumerate(game.players.values(), 1):
        text += f"{i}. <a href='tg://user?id={p.user_id}'>{p.name}</a>\n"

    text += "\n⊱⋅ ───────────── ⋅⊰\n"
    text += "✧ Together we play, together we conquer! ⚡\n"

    # Support button
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("💠 Support", url="https://t.me/NexoraBots_Support")]
    ])

    await update.message.reply_photo(
        photo="https://graph.org/file/79186f4d926011e1fb8e8-a9c682050a7a3539ed.jpg",
        caption=text,
        parse_mode="HTML",
        reply_markup=buttons
    )

# ---------------- END MATCH ----------------
async def endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == 'private':
        await update.message.reply_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵\n\n❌ Use this command in the group only."
        )
        return

    # Admin check
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except:
        await update.message.reply_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n❌ Could not verify admin status."
        )
        return

    if member.status not in ["administrator", "creator"]:
        await update.message.reply_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵\n\n❌ Only group admins can end the match."
        )
        return

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm End Match", callback_data=f"confirm_endmatch:{chat.id}")]
    ])
    await update.message.reply_text(
        " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n⚠️ Are you sure you want to end the current game?",
        reply_markup=buttons
    )

# ---------------- CONFIRM END MATCH ----------------
async def confirm_endmatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # ✅ Always answer callback queries

    # Extract group_id safely
    data = query.data.split(":")
    if len(data) != 2:
        return
    group_id = int(data[1])
    user = query.from_user

    # ---------------- ADMIN CHECK ----------------
    try:
        member = await context.bot.get_chat_member(group_id, user.id)
    except:
        await query.edit_message_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n❌ Could not verify admin."
        )
        return

    if member.status not in ["administrator", "creator"]:
        await query.edit_message_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵』\n\n❌ Only admins can confirm this action."
        )
        return

    # ---------------- ACTIVE GAME CHECK ----------------
    if group_id not in active_games:
        await query.edit_message_text(
            " ⚠️ 𝗘𝗻𝗱 𝗠𝗮𝘁𝗰𝗵 \n\n❌ No active game to end."
        )
        return

    game = active_games[group_id]

    # ---------------- CANCEL PLAYER TIMERS ----------------
    for task in list(game.pick_tasks.values()) + list(game.pick_30_alerts.values()):
        if not task.done():
            task.cancel()
    game.pick_tasks.clear()
    game.pick_30_alerts.clear()

    # ---------------- SAVE USER STATS ----------------
    for p in game.players.values():
        class UserObj:
            def __init__(self, user_id, name, username):
                self.id = user_id
                self.first_name = name
                self.username = username

        u = UserObj(p.user_id, p.name, p.username)
        ensure_user_exists(u)

        update_user_after_game(
            user_id=p.user_id,
            score_delta=getattr(p, "total_score", p.score),
            rounds_played=getattr(p, "rounds_played", 0),
            eliminated=getattr(p, "eliminated", False),
            penalties=getattr(p, "total_penalties", 0),
            won=False
        )

    # ---------------- CLEAR USER REFERENCES ----------------
    for p in game.players.values():
        user_active_game.pop(p.user_id, None)

    # ---------------- REMOVE GAME ----------------
    del active_games[group_id]

    # ---------------- CONFIRM MESSAGE ----------------
    await query.edit_message_text(
        " ✅ 𝗚𝗮𝗺𝗲 𝗘𝗻𝗱𝗲𝗱 \n\n"
        "☑️ Game ended by admin.\n"
        "⏳ All timers cleared."
    )

# -------------------- /USERINFO COMMAND --------------------
async def userinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user stats in a stylish format."""
    user = update.effective_user

    # Ensure all necessary columns exist before querying
    ensure_columns_exist()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Fetch user stats safely
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
『 𝗨𝘀𝗲𝗿 𝗦𝘁𝗮𝘁𝘀 : 𓆩⌬ ‹{display_name}›𓆪 』


🎮 Games Played : {games_played}
🥇 Wins : {wins}
🥈 Losses : {losses}

⊱⋅ ──────────────── ⋅⊰

📊 Win % : {win_pct:.2f}%
⭐ Total Score : {total_score}
🎯 Last Score : {last_score}
🎲 Rounds Played : {rounds_played}
☠️ Eliminations : {eliminations}
⛔ Penalties : {penalties}

⊱⋅ ──────────────── ⋅⊰

✧ one match doesn’t define you — the comeback will! 🚀

▭▭▭▭▭▭▭▭▭▭▭▭▭▭
"""
    await update.message.reply_text(msg, parse_mode="HTML")

# ---------------- Helpers ----------------
def get_all_users_sorted():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT username, games_played, wins, losses, user_id
        FROM users
        ORDER BY wins DESC
    """)
    result = cursor.fetchall()
    conn.close()
    return result

def get_user_rank(user_id):
    all_users = get_all_users_sorted()
    for idx, (username, games_played, wins, losses, uid) in enumerate(all_users, start=1):
        if uid == user_id:
            win_percent = round(wins / games_played * 100, 1) if games_played > 0 else 0
            return {
                "username": username,
                "rank": idx,
                "total_users": len(all_users),
                "total_played": games_played,
                "wins": wins,
                "losses": losses,
                "win_percent": win_percent
            }
    return None

# ---------------- /leaderboard ----------------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    all_users = get_all_users_sorted()
    text = "𝐓𝐎𝐏 𝐏𝐋𝐀𝐘𝐄𝐑𝐒\n\n"

    top_limit = 5
    user_in_top = False
    user_stats = None

    for i, (username, games_played, wins, losses, uid) in enumerate(all_users, start=1):
        if i > top_limit and uid != user_id:
            continue

        win_percent = round(wins / games_played * 100, 1) if games_played > 0 else 0
        highlight = "⭐ " if uid == user_id else ""
        text += f"{i}. {highlight}{username} \n"
        text += f"   🎮 Played: {games_played} |  Wins: {wins} |  Losses: {losses} |  Win %: {win_percent}\n"
        text += f"   🆔 {uid}\n"
        text += "────────────\n"

        if uid == user_id:
            user_in_top = True
            user_stats = {
                "rank": i,
                "username": username,
                "total_played": games_played,
                "wins": wins,
                "losses": losses,
                "win_percent": win_percent
            }

    # If user not in top 5, append their rank explicitly
    if not user_in_top and user_stats is None:
        user_stats = get_user_rank(user_id)
        if user_stats:
            text += f"\n📌 Your Rank:\n"
            text += f"{user_stats['rank']}. {user_stats['username']} \n"
            text += f"  Played: {user_stats['total_played']} |  Wins: {user_stats['wins']} |  Losses: {user_stats['losses']} |  Win %: {user_stats['win_percent']}\n"
            text += f"   🆔 {user_id}\n"
            text += "──────────────\n"

    await update.message.reply_text(text, parse_mode="HTML")

# ---------------- /users_rank ----------------
async def users_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = get_user_rank(user_id)
    if not stats:
        await update.message.reply_text("❌ You are not yet on the leaderboard.")
        return

    text = (
        f"🏆 𝐘𝐎𝐔𝐑 𝐑𝐀𝐍𝐊\n\n"
        f"{stats['rank']}. {stats['username']} \n"
        f"   🎮 Played: {stats['total_played']} |  Wins: {stats['wins']} |  Losses: {stats['losses']} |  Win %: {stats['win_percent']}\n"
        f"   🆔 {user_id}\n"
        "───────────────\n"
    )

    await update.message.reply_text(text, parse_mode="HTML")
# Add new forcestart command handler
async def forcestart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == 'private':
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Use this command in the group only."
        )
        return

    group_id = chat.id

    # Admin check
    try:
        member = await context.bot.get_chat_member(group_id, user.id)
        if member.status not in ["administrator", "creator"]:
            await update.message.reply_text(
                "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Only group admins can use this command."
            )
            return
    except:
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Could not verify admin status."
        )
        return

    # Check if a game exists
    if group_id not in active_games:
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ No active game to start."
        )
        return

    game = active_games[group_id]

    # Check if join phase is active
    if not game.join_phase_active:
        await update.message.reply_text(
            "⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Join phase is already closed!"
        )
        return

    # Check minimum players
    if len(game.players) < MIN_PLAYERS:
        await update.message.reply_text(
            f"⚠️ 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n❌ Not enough players joined ({len(game.players)}/{MIN_PLAYERS})."
        )
        return

    # Cancel join phase timer
    if game.join_timer_task and not game.join_timer_task.done():
        game.join_timer_task.cancel()
        game.join_timer_task = None

    # End join phase and start game
    game.join_phase_active = False
    await context.bot.send_message(
        chat_id=group_id,
        text=f"🚀 𝗙𝗼𝗿𝗰𝗲 𝗦𝘁𝗮𝗿𝘁\n\n✅ Admin has started the game early!"
    )
    await end_join_phase(context, group_id)
# Update register_handlers to include forcestart
def register_handlers(app):
    init_user_table()
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("players", players))
    app.add_handler(CommandHandler("endgame", endmatch))
    app.add_handler(CommandHandler("forcestart", forcestart))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("users_rank", users_rank))
    app.add_handler(
        CallbackQueryHandler(confirm_endmatch, pattern=r"^confirm_endmatch:-?\d+$")
    )
    app.add_handler(
        CallbackQueryHandler(mode_selection, pattern=r"^(start_solo|start_team):-?\d+$")
    )
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, dm_pick_handler))
